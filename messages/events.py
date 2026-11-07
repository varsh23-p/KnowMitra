"""
app/messages/events.py
======================
Flask-SocketIO event handlers for real-time messaging, typing
indicators, online/offline presence, and WebRTC call signalling.

All events check Flask-Login's current_user so unauthenticated
connections are silently rejected.
"""

import logging
from datetime import datetime, timezone, timedelta
from flask import request
from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from ..models import db, Message, User, MessageAttachment, CallHistory, Notification
from sqlalchemy import or_, and_

from ..services.notification_service import push_notification

log = logging.getLogger(__name__)

_IST = timedelta(hours=5, minutes=30)

# {user_id: set(sid)} — track every socket session per user
_online_users: dict[int, set] = {}


def _now_ist() -> str:
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return (utc + _IST).strftime('%I:%M %p').lstrip('0') or '12:00 AM'


def _now_ist_full() -> str:
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return (utc + _IST).strftime('%b %d, %I:%M %p')


def _room(a: int, b: int) -> str:
    """Deterministic room name for two users (order-independent)."""
    return f'chat_{min(a, b)}_{max(a, b)}'


def _are_connected(uid_a: int, uid_b: int) -> bool:
    from ..models import ExchangeRequest
    return ExchangeRequest.query.filter(
        or_(
            and_(ExchangeRequest.sender_id == uid_a,
                 ExchangeRequest.receiver_id == uid_b),
            and_(ExchangeRequest.sender_id == uid_b,
                 ExchangeRequest.receiver_id == uid_a),
        ),
        ExchangeRequest.status.in_(['accepted', 'completed'])
    ).first() is not None


def _serialize(msg: Message, viewer_id: int) -> dict:
    """Convert a Message row to a JSON-safe dict."""
    att = None
    if msg.attachment:
        att = {
            'filename':  msg.attachment.filename,
            'mime_type': msg.attachment.mime_type,
            'file_size': msg.attachment.file_size,
            # URL the browser uses to load the file (served by Flask route)
            'url':       f'/messages/file/{msg.attachment.filename}',
        }
    utc_dt = msg.created_at or datetime.utcnow()
    ist_dt = utc_dt + _IST
    return {
        'id':           msg.id,
        'sender_id':    msg.sender_id,
        'receiver_id':  msg.receiver_id,
        'content':      msg.content,
        'msg_type':     msg.msg_type or 'text',
        'is_read':      msg.is_read,
        'deleted_for_all': bool(msg.deleted_for_all),
        'is_mine':      msg.sender_id == viewer_id,
        'time_short':   ist_dt.strftime('%I:%M %p').lstrip('0') or '12:00 AM',
        'time_full':    ist_dt.strftime('%b %d, %I:%M %p'),
        'date':         ist_dt.strftime('%B %d, %Y'),
        'attachment':   att,
    }


def register_socket_events(sio):
    """Attach all SocketIO event handlers to *sio*."""

    # ── connect / disconnect ───────────────────────────────────

    @sio.on('connect')
    def on_connect():
        if not current_user.is_authenticated:
            return False   # reject
        uid = current_user.id
        _online_users.setdefault(uid, set()).add(request.sid)
        # Update last_seen
        current_user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        emit('presence', {'user_id': uid, 'online': True}, broadcast=True)

    @sio.on('disconnect')
    def on_disconnect():
        if not current_user.is_authenticated:
            return
        uid = current_user.id
        sids = _online_users.get(uid, set())
        sids.discard(request.sid)
        if not sids:
            _online_users.pop(uid, None)
            current_user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
            emit('presence', {'user_id': uid, 'online': False}, broadcast=True)

    # ── join / leave conversation room ────────────────────────

    @sio.on('join_conversation')
    def on_join(data):
        if not current_user.is_authenticated:
            return
        partner_id = int(data.get('partner_id', 0))
        if not partner_id:
            return
        if not _are_connected(current_user.id, partner_id):
            return
        room = _room(current_user.id, partner_id)
        join_room(room)

        # Mark incoming messages as read
        Message.query.filter_by(
            sender_id=partner_id,
            receiver_id=current_user.id,
            is_read=False
        ).update({'is_read': True})
        db.session.commit()

        # Tell the partner their messages were read
        emit('messages_read', {'by': current_user.id}, room=room,
             skip_sid=request.sid)

        # Send online presence info
        partner_online = partner_id in _online_users
        partner = db.session.get(User, partner_id)
        last_seen_str = ''
        if partner and partner.last_seen:
            ist_ls = partner.last_seen + _IST
            last_seen_str = ist_ls.strftime('Last seen %b %d at %I:%M %p').lstrip('0')

        emit('partner_status', {
            'online':    partner_online,
            'last_seen': last_seen_str,
        })

    @sio.on('leave_conversation')
    def on_leave(data):
        if not current_user.is_authenticated:
            return
        partner_id = int(data.get('partner_id', 0))
        if partner_id:
            leave_room(_room(current_user.id, partner_id))

    # ── send text message ─────────────────────────────────────

    @sio.on('send_message')
    def on_send_message(data):
        if not current_user.is_authenticated:
            return
        partner_id = int(data.get('partner_id', 0))
        content    = (data.get('content') or '').strip()

        if not partner_id or not content:
            return
        if len(content) > 2000:
            emit('error', {'msg': 'Message too long (max 2000 chars).'})
            return
        if not _are_connected(current_user.id, partner_id):
            emit('error', {'msg': 'Not connected with this user.'})
            return

        msg = Message(
            sender_id=current_user.id,
            receiver_id=partner_id,
            content=content,
            msg_type='text',
        )
        db.session.add(msg)
        db.session.commit()

        payload = _serialize(msg, current_user.id)
        room    = _room(current_user.id, partner_id)

        # Send to both participants in the room
        emit('new_message', payload, room=room)

        # If partner is not in the room right now, send a notification event
        partner_in_room = partner_id in _online_users
        if partner_in_room:
            # Serialise from partner's perspective
            partner_payload = _serialize(msg, partner_id)
            emit('new_message_notify', partner_payload,
                 room=f'user_{partner_id}')

        # ── Create a notification for the receiver ────────────────
        sender = current_user
        push_notification(
            partner_id,
            title=f'{sender.full_name} sent you a message',
            body='',  # Never include message content in notifications
            link=f'/messages/conversation/{sender.id}',
            icon='fa-envelope',
            notif_type='message',
        )

    # ── user-specific room (for notifications) ────────────────

    @sio.on('join_user_room')
    def on_join_user_room():
        if not current_user.is_authenticated:
            return
        join_room(f'user_{current_user.id}')

    # ── typing indicator ──────────────────────────────────────

    @sio.on('typing')
    def on_typing(data):
        if not current_user.is_authenticated:
            return
        partner_id = int(data.get('partner_id', 0))
        if not partner_id:
            return
        room = _room(current_user.id, partner_id)
        emit('typing', {
            'user_id': current_user.id,
            'typing':  bool(data.get('typing', False)),
        }, room=room, skip_sid=request.sid)

    # ── delete message ────────────────────────────────────────

    @sio.on('delete_message')
    def on_delete_message(data):
        if not current_user.is_authenticated:
            return
        msg_id    = int(data.get('msg_id', 0))
        delete_for = data.get('mode', 'me')   # 'me' or 'everyone'

        msg = db.session.get(Message, msg_id)
        if not msg:
            return

        uid = current_user.id
        # Authorization
        if uid not in (msg.sender_id, msg.receiver_id):
            return
        if delete_for == 'everyone' and uid != msg.sender_id:
            emit('error', {'msg': 'Only the sender can delete for everyone.'})
            return

        if delete_for == 'everyone':
            msg.deleted_for_all = True
        elif uid == msg.sender_id:
            msg.deleted_by_sender = True
        else:
            msg.deleted_by_receiver = True

        db.session.commit()

        room = _room(msg.sender_id, msg.receiver_id)
        if delete_for == 'everyone':
            emit('message_deleted_all', {'msg_id': msg_id}, room=room)
        else:
            emit('message_deleted_me', {'msg_id': msg_id})

    # ── mark messages read ─────────────────────────────────────

    @sio.on('mark_read')
    def on_mark_read(data):
        if not current_user.is_authenticated:
            return
        partner_id = int(data.get('partner_id', 0))
        if not partner_id:
            return
        Message.query.filter_by(
            sender_id=partner_id,
            receiver_id=current_user.id,
            is_read=False,
        ).update({'is_read': True})
        db.session.commit()
        room = _room(current_user.id, partner_id)
        emit('messages_read', {'by': current_user.id}, room=room,
             skip_sid=request.sid)

    # ══════════════════════════════════════════════════════════
    # WebRTC SIGNALLING — audio & video calls
    # ══════════════════════════════════════════════════════════

    @sio.on('call_initiate')
    def on_call_initiate(data):
        if not current_user.is_authenticated:
            return
        callee_id = int(data.get('callee_id', 0))
        call_type = data.get('call_type', 'audio')   # audio / video
        if not callee_id:
            return
        if not _are_connected(current_user.id, callee_id):
            emit('error', {'msg': 'You must have an accepted exchange to call this user.'})
            return

        caller = current_user
        call = CallHistory(
            caller_id=caller.id,
            callee_id=callee_id,
            call_type=call_type,
            status='calling',
        )
        db.session.add(call)
        db.session.commit()
        log.info('[CALL] call_initiate call_id=%s caller=%s callee=%s type=%s',
                 call.id, caller.id, callee_id, call_type)

        emit('incoming_call', {
            'call_id':    call.id,
            'caller_id':  caller.id,
            'caller_name': caller.full_name,
            'call_type':  call_type,
        }, room=f'user_{callee_id}')

        # ── Create a notification for the callee ───────────────
        push_notification(
            callee_id,
            title=f'{caller.full_name} is calling you',
            body=f'Incoming {call_type} call',
            link=f'/messages/conversation/{caller.id}',
            icon='fa-phone' if call_type == 'audio' else 'fa-video',
            notif_type=f'call_{call_type}',
        )

        # Tell the caller their call ID so they can cancel it correctly
        emit('call_ringing', {'call_id': call.id, 'call_type': call_type})

    @sio.on('call_accept')
    def on_call_accept(data):
        if not current_user.is_authenticated:
            return
        call_id = int(data.get('call_id', 0))
        call = db.session.get(CallHistory, call_id)
        if not call or call.callee_id != current_user.id:
            return
        call.status = 'accepted'
        db.session.commit()
        log.info('[CALL] call_accept call_id=%s callee=%s', call_id, current_user.id)
        emit('call_accepted', {'call_id': call_id},
             room=f'user_{call.caller_id}')

    @sio.on('call_ready')
    def on_call_ready(data):
        """Callee has navigated to the conversation page and is ready
        to receive the WebRTC SDP offer."""
        if not current_user.is_authenticated:
            return
        call_id = int(data.get('call_id', 0))
        call = db.session.get(CallHistory, call_id)
        if not call:
            return
        # Only the callee should send this
        if current_user.id != call.callee_id:
            return
        emit('call_ready', {
            'call_id':   call_id,
            'call_type': call.call_type,  # caller needs this to request correct media
        }, room=f'user_{call.caller_id}')
        log.info('[CALL] call_ready call_id=%s callee=%s type=%s',
                 call_id, current_user.id, call.call_type)

    @sio.on('call_reject')
    def on_call_reject(data):
        if not current_user.is_authenticated:
            return
        call_id = int(data.get('call_id', 0))
        call = db.session.get(CallHistory, call_id)
        if not call:
            return
        call.status = 'rejected'
        call.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        emit('call_rejected', {'call_id': call_id},
             room=f'user_{call.caller_id}')

    @sio.on('call_cancel')
    def on_call_cancel(data):
        """Caller cancels an outgoing call before it's answered."""
        if not current_user.is_authenticated:
            return
        call_id = int(data.get('call_id', 0))
        call = db.session.get(CallHistory, call_id)
        if not call:
            return
        if call.caller_id != current_user.id:
            return
        call.status = 'missed'
        call.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        emit('call_cancelled', {'call_id': call_id},
             room=f'user_{call.callee_id}')

    @sio.on('call_end')
    def on_call_end(data):
        if not current_user.is_authenticated:
            return
        call_id  = int(data.get('call_id', 0))
        duration = int(data.get('duration', 0))
        call = db.session.get(CallHistory, call_id)
        if not call:
            return
        if current_user.id not in (call.caller_id, call.callee_id):
            return
        call.status     = 'ended'
        call.ended_at   = datetime.now(timezone.utc).replace(tzinfo=None)
        call.duration_s = duration
        db.session.commit()
        other_id = call.callee_id if current_user.id == call.caller_id else call.caller_id
        emit('call_ended', {'call_id': call_id, 'duration': duration},
             room=f'user_{other_id}')

    # ── WebRTC SDP offer / answer / ICE ──────────────────────

    @sio.on('webrtc_offer')
    def on_webrtc_offer(data):
        if not current_user.is_authenticated:
            return
        target_id = int(data.get('target_id', 0))
        log.info('[WebRTC] offer from=%s to=%s call_id=%s type=%s',
                 current_user.id, target_id, data.get('call_id'), data.get('call_type'))
        emit('webrtc_offer', {
            'offer':     data.get('offer'),
            'caller_id': current_user.id,
            'call_id':   data.get('call_id'),
            'call_type': data.get('call_type', 'audio'),
        }, room=f'user_{target_id}')

    @sio.on('webrtc_answer')
    def on_webrtc_answer(data):
        if not current_user.is_authenticated:
            return
        target_id = int(data.get('target_id', 0))
        log.info('[WebRTC] answer from=%s to=%s call_id=%s',
                 current_user.id, target_id, data.get('call_id'))
        emit('webrtc_answer', {
            'answer':    data.get('answer'),
            'callee_id': current_user.id,
            'call_id':   data.get('call_id'),
        }, room=f'user_{target_id}')

    @sio.on('webrtc_ice')
    def on_webrtc_ice(data):
        if not current_user.is_authenticated:
            return
        target_id = int(data.get('target_id', 0))
        log.debug('[WebRTC] ICE candidate from=%s to=%s', current_user.id, target_id)
        emit('webrtc_ice', {
            'candidate': data.get('candidate'),
            'from_id':   current_user.id,
        }, room=f'user_{target_id}')
