"""
messages/routes.py
==================
Student-to-student messaging system.

Timestamps:
  - Stored in SQLite as naive UTC (datetime.utcnow).
  - Converted to IST (UTC+5:30) before display using _to_ist().
  - Displayed in 12-hour AM/PM format (e.g. 11:32 AM).
  - Both the Jinja template (page-load path) and the JSON
    serialiser (_serialize_msg, used by AJAX send + poll)
    use the same helper so every path shows IST.
"""

from datetime import datetime, timezone, timedelta
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort, current_app,
                   send_from_directory)
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func
from ..models import db, Message, User, ExchangeRequest

messages_bp = Blueprint('messages', __name__)

MAX_MESSAGE_LENGTH = 2000
POLL_INTERVAL_MS   = 4000        # client-side polling interval (ms)

# IST offset: UTC + 5 hours 30 minutes
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _to_ist(dt: datetime) -> datetime:
    """
    Convert a naive-UTC datetime (as stored by SQLite/SQLAlchemy) to IST.

    We treat every datetime stored in the DB as UTC, add the IST offset,
    and return a new naive datetime that already represents IST wall-clock
    time.  This is safe and consistent: no ambiguity about whether a stored
    value is local or UTC because we always write UTC (default=datetime.utcnow).
    """
    if dt is None:
        return dt
    return dt + _IST_OFFSET


def _fmt_time(dt: datetime) -> str:
    """Return IST time in 12-hour AM/PM format, e.g. '11:32 AM'."""
    return _to_ist(dt).strftime('%I:%M %p').lstrip('0') or '12:00 AM'


def _fmt_date(dt: datetime) -> str:
    """Return IST date, e.g. 'June 15, 2026'."""
    return _to_ist(dt).strftime('%B %d, %Y')


def _fmt_date_short(dt: datetime) -> str:
    """Return IST short date for sidebar preview, e.g. 'Jun 15'."""
    return _to_ist(dt).strftime('%b %d')


# ── Register helpers as Jinja filters so templates can call them ─
# Used in conversation.html and inbox.html as:
#   {{ msg.created_at | ist_time }}
#   {{ msg.created_at | ist_date }}
#   {{ msg.created_at | ist_date_short }}

@messages_bp.record_once
def _register_jinja_filters(state):
    app = state.app
    app.jinja_env.filters['ist_time']       = _fmt_time
    app.jinja_env.filters['ist_date']       = _fmt_date
    app.jinja_env.filters['ist_date_short'] = _fmt_date_short


def _are_connected(user_a_id: int, user_b_id: int) -> bool:
    """
    Return True if *user_a* and *user_b* have an accepted or completed
    exchange request between them (in either direction).
    """
    return ExchangeRequest.query.filter(
        or_(
            and_(ExchangeRequest.sender_id   == user_a_id,
                 ExchangeRequest.receiver_id == user_b_id),
            and_(ExchangeRequest.sender_id   == user_b_id,
                 ExchangeRequest.receiver_id == user_a_id),
        ),
        ExchangeRequest.status.in_(['accepted', 'completed']),
    ).first() is not None


def _get_conversations(user_id: int) -> list[dict]:
    """
    Build the conversation list for *user_id*.
    Each entry has: partner (User), last_msg (Message), unread (int).
    Sorted by latest message descending.
    """
    # Find all distinct conversation partner IDs
    sent_to = (db.session.query(Message.receiver_id.label('partner_id'))
               .filter(Message.sender_id == user_id))
    received_from = (db.session.query(Message.sender_id.label('partner_id'))
                     .filter(Message.receiver_id == user_id))
    partner_ids = {row.partner_id for row in sent_to.union(received_from).all()}

    conversations = []
    for pid in partner_ids:
        partner = db.session.get(User, pid)
        if not partner:
            continue
        last_msg = (Message.query
                    .filter(or_(
                        and_(Message.sender_id == user_id,
                             Message.receiver_id == pid),
                        and_(Message.sender_id == pid,
                             Message.receiver_id == user_id),
                    ))
                    .order_by(Message.created_at.desc())
                    .first())
        unread = (Message.query
                  .filter_by(sender_id=pid, receiver_id=user_id, is_read=False)
                  .count())
        conversations.append({
            'partner':          partner,
            'last_msg':         last_msg,
            'last_msg_time':    _fmt_date_short(last_msg.created_at),
            'unread':           unread,
        })

    conversations.sort(key=lambda c: c['last_msg'].created_at, reverse=True)
    return conversations


def _total_unread(user_id: int) -> int:
    """Return total unread messages for *user_id*."""
    return Message.query.filter_by(receiver_id=user_id, is_read=False).count()


def _serialize_msg(m: Message, current_user_id: int) -> dict:
    """
    Serialize a Message to a JSON-safe dict for the AJAX endpoints.
    All times are converted from UTC to IST before formatting.
    """
    return {
        'id':          m.id,
        'content':     m.content,
        'is_mine':     m.sender_id == current_user_id,
        # time_short: 12-hour IST format shown inside the bubble, e.g. "11:32 AM"
        'time_short':  _fmt_time(m.created_at),
        # created_at: full IST for the date-separator logic
        'created_at':  _fmt_time(m.created_at),
        # date: IST date for date-separator grouping
        'date':        _fmt_date(m.created_at),
        'sender_name': m.sender.full_name,
        'sender_id':   m.sender_id,
    }


# ══════════════════════════════════════════════════════════════════
# Inbox — conversation list
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/')
@login_required
def inbox():
    """Render the inbox page with all conversations and total unread count."""
    conversations = _get_conversations(current_user.id)
    total_unread  = _total_unread(current_user.id)

    return render_template('messages/inbox.html',
                           conversations=conversations,
                           total_unread=total_unread)


# ══════════════════════════════════════════════════════════════════
# Conversation — view + send (GET renders, POST sends via form)
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/conversation/<int:user_id>', methods=['GET', 'POST'])
@login_required
def conversation(user_id):
    """
    GET  → render the conversation page with message history.
    POST → validate and send a message (form-submit fallback; the
           JS client uses the AJAX endpoint instead for a smoother UX).
    """
    partner = User.query.get_or_404(user_id)

    # ── Access control ─────────────────────────────────────────
    if user_id == current_user.id:
        flash("You can't message yourself.", 'warning')
        return redirect(url_for('messages.inbox'))

    if not _are_connected(current_user.id, user_id):
        flash('You can only message students you have an accepted or '
              'completed exchange with.', 'warning')
        return redirect(url_for('messages.inbox'))

    # ── Handle POST (form fallback) ─────────────────────────────
    if request.method == 'POST':
        content = request.form.get('content', '').strip()

        if not content:
            flash('Message cannot be empty.', 'danger')
            return redirect(url_for('messages.conversation', user_id=user_id))

        if len(content) > MAX_MESSAGE_LENGTH:
            flash(f'Message is too long (max {MAX_MESSAGE_LENGTH} characters).',
                  'danger')
            return redirect(url_for('messages.conversation', user_id=user_id))

        msg = Message(
            sender_id=current_user.id,
            receiver_id=user_id,
            content=content,
        )
        db.session.add(msg)
        db.session.commit()
        return redirect(url_for('messages.conversation', user_id=user_id))

    # ── GET: load messages and mark as read ──────────────────────
    msgs = (Message.query
            .filter(or_(
                and_(Message.sender_id   == current_user.id,
                     Message.receiver_id == user_id),
                and_(Message.sender_id   == user_id,
                     Message.receiver_id == current_user.id),
            ))
            .order_by(Message.created_at.asc(), Message.id.asc()).all())

    # Mark incoming messages as read
    Message.query.filter_by(
        sender_id=user_id, receiver_id=current_user.id, is_read=False
    ).update({'is_read': True})
    db.session.commit()

    # Also load all conversations for the sidebar
    conversations = _get_conversations(current_user.id)

    return render_template('messages/conversation.html',
                           partner=partner,
                           messages=msgs,
                           conversations=conversations,
                           poll_interval=POLL_INTERVAL_MS)


# ══════════════════════════════════════════════════════════════════
# AJAX: send a message (returns JSON — no page reload)
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/send/<int:user_id>', methods=['POST'])
@login_required
def send_ajax(user_id):
    """AJAX endpoint to send a message and return the created message as JSON."""
    partner = User.query.get_or_404(user_id)

    # ── Access control ─────────────────────────────────────────
    if user_id == current_user.id:
        return jsonify({'error': 'You cannot message yourself.'}), 403

    if not _are_connected(current_user.id, user_id):
        return jsonify({'error': 'You can only message students you have an '
                                 'accepted or completed exchange with.'}), 403

    content = request.form.get('content', '').strip()

    # ── Validation ──────────────────────────────────────────────
    if not content:
        return jsonify({'error': 'Message cannot be empty.'}), 400

    if len(content) > MAX_MESSAGE_LENGTH:
        return jsonify({'error': f'Message is too long (max '
                                 f'{MAX_MESSAGE_LENGTH} characters).'}), 400

    msg = Message(
        sender_id=current_user.id,
        receiver_id=user_id,
        content=content,
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify(_serialize_msg(msg, current_user.id))


# ══════════════════════════════════════════════════════════════════
# AJAX: poll for new messages
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/poll/<int:user_id>')
@login_required
def poll(user_id):
    """
    Return messages newer than *since* (by ID) as JSON.
    Also marks incoming messages as read.
    """
    # ── Access control ─────────────────────────────────────────
    if user_id == current_user.id:
        return jsonify({'error': 'Invalid request.'}), 400

    if not _are_connected(current_user.id, user_id):
        return jsonify({'error': 'Not authorized.'}), 403

    since_id = request.args.get('since', 0, type=int)

    msgs = (Message.query
            .filter(or_(
                and_(Message.sender_id   == current_user.id,
                     Message.receiver_id == user_id),
                and_(Message.sender_id   == user_id,
                     Message.receiver_id == current_user.id),
            ),
                Message.id > since_id)
            .order_by(Message.created_at.asc(), Message.id.asc()).all())

    # Mark incoming messages as read
    Message.query.filter_by(
        sender_id=user_id, receiver_id=current_user.id, is_read=False
    ).update({'is_read': True})
    db.session.commit()

    return jsonify([_serialize_msg(m, current_user.id) for m in msgs])


# ══════════════════════════════════════════════════════════════════
# AJAX: unread count badge (for navbar polling)
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/unread-count')
@login_required
def unread_count():
    """Return the total unread message count as JSON."""
    return jsonify({'count': _total_unread(current_user.id)})

# ══════════════════════════════════════════════════════════════════
# File upload (images + audio) for messages
# ══════════════════════════════════════════════════════════════════

import os
import uuid
from werkzeug.utils import secure_filename
from ..models import MessageAttachment

ALLOWED_IMG  = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
ALLOWED_AUDIO = {'webm', 'ogg', 'mp3', 'wav', 'm4a'}
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB


def _allowed_file(filename, allowed_set):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in allowed_set)


@messages_bp.route('/upload/<int:user_id>', methods=['POST'])
@login_required
def upload_file(user_id):
    """Upload an image or audio attachment and create a message."""
    partner = User.query.get_or_404(user_id)

    if user_id == current_user.id:
        return jsonify({'error': 'Cannot send to yourself.'}), 403

    if not _are_connected(current_user.id, user_id):
        return jsonify({'error': 'Not connected.'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided.'}), 400

    # Determine type
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext in ALLOWED_IMG:
        msg_type = 'image'
        allowed = ALLOWED_IMG
    elif ext in ALLOWED_AUDIO:
        msg_type = 'audio'
        allowed = ALLOWED_AUDIO
    else:
        return jsonify({'error': f'File type .{ext} not allowed. '
                                 f'Images: {", ".join(ALLOWED_IMG)}. '
                                 f'Audio: {", ".join(ALLOWED_AUDIO)}.'}), 400

    if not _allowed_file(file.filename, allowed):
        return jsonify({'error': 'Invalid file extension.'}), 400

    # Check file size via content-length header
    if request.content_length and request.content_length > MAX_FILE_SIZE:
        return jsonify({'error': 'File too large (max 10 MB).'}), 413

    # Generate safe unique filename
    safe_ext = secure_filename(file.filename).rsplit('.', 1)[-1].lower()
    unique_name = f"msg_{current_user.id}_{uuid.uuid4().hex[:12]}.{safe_ext}"

    # Save to uploads/messages/
    msg_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'messages')
    os.makedirs(msg_dir, exist_ok=True)
    file.save(os.path.join(msg_dir, unique_name))

    # Create the message
    msg = Message(
        sender_id=current_user.id,
        receiver_id=user_id,
        content=request.form.get('caption', '') or f'[{msg_type}]',
        msg_type=msg_type,
    )
    db.session.add(msg)
    db.session.flush()  # get msg.id

    # Create attachment record
    att = MessageAttachment(
        message_id=msg.id,
        filename=unique_name,
        original=secure_filename(file.filename),
        mime_type=file.content_type or '',
        file_size=request.content_length or 0,
    )
    db.session.add(att)
    db.session.commit()

    # ── Emit real-time SocketIO event so both participants see the image ──
    # Re-import the serializer (avoids circular import at module level)
    from .events import _serialize, _room, push_notification
    payload = _serialize(msg, current_user.id)
    room    = _room(current_user.id, user_id)

    try:
        from flask_socketio import emit
        # Emit to both participants in the room
        emit('new_message', payload, room=room)
        # Emit from the receiver's perspective too (is_mine = False for them)
        receiver_payload = _serialize(msg, user_id)
        emit('new_message', receiver_payload, room=f'user_{user_id}')
    except Exception:
        pass  # SocketIO may not be available in CLI/test context

    # Also create a notification for the receiver
    push_notification(
        user_id,
        title=f'{current_user.full_name} sent you a message',
        body='',
        link=f'/messages/conversation/{current_user.id}',
        icon='fa-envelope',
        notif_type='message',
    )

    return jsonify({
        'id':         msg.id,
        'msg_type':   msg_type,
        'filename':   unique_name,
        'file_url':   f'/messages/file/{unique_name}',
        'content':    msg.content,
        'sender_id':  msg.sender_id,
        'time_short': _fmt_time(msg.created_at),
        'attachment': {
            'filename':  att.filename,
            'mime_type': att.mime_type,
            'url':       f'/messages/file/{att.filename}',
        },
    })


@messages_bp.route('/file/<path:filename>')
@login_required
def serve_file(filename):
    """Serve a message attachment file — only to conversation participants."""
    att = MessageAttachment.query.filter_by(filename=filename).first()
    if not att:
        abort(404)

    msg = att.message
    if current_user.id not in (msg.sender_id, msg.receiver_id):
        abort(403)

    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'messages')
    return send_from_directory(upload_dir, filename)


# ══════════════════════════════════════════════════════════════════
# Message deletion (AJAX — soft delete)
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/delete/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(msg_id):
    """
    Soft-delete a message.

    POST body:
        mode = 'me'       → hide only for the requesting user
        mode = 'everyone' → hide for both (sender only)

    Never physically deletes the row — sets boolean flags.
    """
    msg = db.session.get(Message, msg_id)
    if not msg:
        return jsonify({'error': 'Message not found.'}), 404

    uid   = current_user.id
    mode  = request.form.get('mode', 'me')

    # Authorization
    if uid not in (msg.sender_id, msg.receiver_id):
        return jsonify({'error': 'Not authorized.'}), 403

    if mode == 'everyone':
        if uid != msg.sender_id:
            return jsonify({'error': 'Only the sender can delete for everyone.'}), 403
        msg.deleted_for_all = True
    else:
        if uid == msg.sender_id:
            msg.deleted_by_sender = True
        else:
            msg.deleted_by_receiver = True

    db.session.commit()
    return jsonify({'ok': True, 'msg_id': msg_id, 'mode': mode})


# ══════════════════════════════════════════════════════════════════
# Online status (AJAX fallback)
# ══════════════════════════════════════════════════════════════════

@messages_bp.route('/status/<int:user_id>')
@login_required
def user_status(user_id):
    """Return online/offline + last-seen for a user."""
    user = User.query.get_or_404(user_id)
    from .events import _online_users
    online = user_id in _online_users

    last_seen = ''
    if user.last_seen:
        ist_ls = user.last_seen + _IST_OFFSET
        last_seen = ist_ls.strftime('Last seen %b %d at %I:%M %p').lstrip('0')

    return jsonify({
        'user_id':   user_id,
        'online':    online,
        'last_seen': last_seen,
    })


# ══════════════════════════════════════════════════════════════════
# Call history
# ══════════════════════════════════════════════════════════════════

from ..models import CallHistory

@messages_bp.route('/calls')
@login_required
def call_history():
    """Show call history for the current user."""
    calls = CallHistory.query.filter(
        or_(CallHistory.caller_id == current_user.id,
            CallHistory.callee_id == current_user.id)
    ).order_by(CallHistory.started_at.desc()).limit(20).all()

    call_list = []
    for c in calls:
        other = c.callee if c.caller_id == current_user.id else c.caller
        ist_start = c.started_at + _IST_OFFSET if c.started_at else ''
        call_list.append({
            'id':          c.id,
            'other_name':  other.full_name if other else 'Unknown',
            'other_id':    other.id if other else 0,
            'call_type':   c.call_type,
            'status':      c.status,
            'duration':    c.duration_s,
            'started_at':  ist_start.strftime('%b %d, %I:%M %p') if ist_start else '',
            'is_caller':   c.caller_id == current_user.id,
        })

    return jsonify(call_list)
