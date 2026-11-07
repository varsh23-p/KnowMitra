"""
exchanges/routes.py
===================
Complete skill exchange request system.

Operations:
  - Send a request (with skill selection + personalized message)
  - Accept an incoming request
  - Reject an incoming request
  - Cancel a pending/accepted request (by sender)
  - Mark an accepted request as completed (by either party)

Status flow:
    pending  →  accepted  →  completed
    pending  →  rejected
    pending  →  cancelled   (by sender)
    accepted →  cancelled   (by sender)

  Terminal states (rejected / cancelled / completed) cannot transition.

Security:
  - Only the receiver can accept / reject.
  - Only the sender can cancel.
  - Either party can mark completed (once accepted).
  - Duplicate pending/accepted requests between the same pair are blocked.
  - Skill IDs are validated: requested skill must be in receiver's teaching
    list, offered skill must be in sender's teaching list.
"""

from datetime import datetime, timezone

_NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, consistent with existing DB
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request)
from flask_login import login_required, current_user
from ..models import db, ExchangeRequest, User, Skill, Notification
from ..services.notification_service import push_notification

exchanges_bp = Blueprint('exchanges', __name__)

# ── Allowed state transitions ────────────────────────────────────
# Maps current status → set of statuses it can move to.
_TRANSITIONS: dict[str, set[str]] = {
    'pending':  {'accepted', 'rejected', 'cancelled'},
    'accepted': {'completed', 'cancelled'},
    # terminal states — no transitions
    'rejected':  set(),
    'cancelled': set(),
    'completed': set(),
}

MAX_MESSAGE_LENGTH = 500


def _notify(user_id: int, title: str, body: str, link: str,
            icon: str = 'fa-exchange-alt') -> None:
    """Create an in-app notification for the given user."""
    n = Notification(user_id=user_id, title=title, body=body,
                     link=link, icon=icon)
    db.session.add(n)


def _can_transition(current: str, target: str) -> bool:
    """Return True if moving from *current* to *target* is allowed."""
    return target in _TRANSITIONS.get(current, set())


def _other_party(req: ExchangeRequest) -> User:
    """Return the user on the other side of *req* relative to current_user."""
    return req.receiver if req.sender_id == current_user.id else req.sender


# ══════════════════════════════════════════════════════════════════
# List all exchanges — with sent/received separation
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/')
@login_required
def index():
    """
    Render the exchanges page with tabbed views.
    Each tab shows sent and received requests with direction badges.
    """
    tab = request.args.get('tab', 'pending')

    uid = current_user.id

    # Base query: requests involving the current user
    base = ExchangeRequest.query.filter(
        (ExchangeRequest.sender_id == uid) |
        (ExchangeRequest.receiver_id == uid)
    )

    pending = (base.filter_by(status='pending')
                   .order_by(ExchangeRequest.created_at.desc()).all())

    accepted = (base.filter_by(status='accepted')
                    .order_by(ExchangeRequest.updated_at.desc()).all())

    completed = (base.filter_by(status='completed')
                     .order_by(ExchangeRequest.updated_at.desc()).all())

    closed = (base.filter(ExchangeRequest.status.in_(
                  ['rejected', 'cancelled']))
                 .order_by(ExchangeRequest.updated_at.desc()).all())

    return render_template('exchanges/index.html',
                           pending=pending,
                           accepted=accepted,
                           completed=completed,
                           closed=closed,
                           tab=tab)


# ══════════════════════════════════════════════════════════════════
# Send a request
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/send/<int:receiver_id>', methods=['GET', 'POST'])
@login_required
def send(receiver_id):
    """GET → show the send form.  POST → validate and create the request."""

    receiver = User.query.get_or_404(receiver_id)

    # ── Guard: can't send to yourself ──────────────────────────
    if receiver_id == current_user.id:
        flash("You can't send a request to yourself.", 'warning')
        return redirect(url_for('matching.matches'))

    # ── Guard: block duplicate pending/accepted requests ────────
    # Check both directions: A→B and B→A
    duplicate = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == current_user.id) &
         (ExchangeRequest.receiver_id == receiver_id)) |
        ((ExchangeRequest.sender_id == receiver_id) &
         (ExchangeRequest.receiver_id == current_user.id))
    ).filter(ExchangeRequest.status.in_(['pending', 'accepted'])).first()

    if duplicate:
        flash('You already have an active request with this student.', 'warning')
        return redirect(url_for('profile.view', user_id=receiver_id))

    # ── Handle POST ────────────────────────────────────────────
    if request.method == 'POST':
        skill_requested_id = request.form.get('skill_requested', type=int)
        skill_offered_id   = request.form.get('skill_offered', type=int)
        message            = request.form.get('message', '').strip()

        errors: list[str] = []

        # ── Validate skill_requested ─────────────────────────────
        # Must be a real skill that the RECEIVER can teach
        skill_requested = None
        if not skill_requested_id:
            errors.append('Please select a skill you want to learn.')
        else:
            skill_requested = db.session.get(Skill, skill_requested_id)
            if not skill_requested:
                errors.append('Invalid skill selected.')
            else:
                # Verify the receiver actually teaches this skill
                receiver_teaching_ids = {s.id for s in receiver.teaching_skills}
                if skill_requested_id not in receiver_teaching_ids:
                    errors.append(
                        f'{receiver.full_name.split()[0]} does not teach '
                        f'"{skill_requested.name}".'
                    )

        # ── Validate skill_offered ──────────────────────────────
        # Must be a real skill that the SENDER (current user) can teach
        skill_offered = None
        if not skill_offered_id:
            errors.append('Please select a skill you offer to teach.')
        else:
            skill_offered = db.session.get(Skill, skill_offered_id)
            if not skill_offered:
                errors.append('Invalid skill selected.')
            else:
                my_teaching_ids = {s.id for s in current_user.teaching_skills}
                if skill_offered_id not in my_teaching_ids:
                    errors.append(
                        f'You don\'t currently teach "{skill_offered.name}". '
                        f'Add it to your skills first.'
                    )

        # ── Validate message ─────────────────────────────────────
        if len(message) > MAX_MESSAGE_LENGTH:
            errors.append(
                f'Message cannot exceed {MAX_MESSAGE_LENGTH} characters.'
            )

        # ── Return on errors ────────────────────────────────────
        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('exchanges.send', receiver_id=receiver_id))

        # ── Create the request ───────────────────────────────────
        req = ExchangeRequest(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            skill_requested_id=skill_requested_id,
            skill_offered_id=skill_offered_id,
            message=message or None,
            status='pending',
        )
        db.session.add(req)

        push_notification(
            receiver_id,
            title=f'{current_user.full_name} sent you an exchange request!',
            body=message[:100] if message else 'Check your requests.',
            link=url_for('exchanges.index', tab='pending'),
            icon='fa-handshake',
            notif_type='exchange_request',
        )
        db.session.commit()

        flash('Exchange request sent successfully!', 'success')
        return redirect(url_for('exchanges.index', tab='pending'))

    # ── GET: render the form ────────────────────────────────────
    my_teaching    = current_user.teaching_skills.all()
    their_teaching = receiver.teaching_skills.all()

    return render_template('exchanges/send.html',
                           receiver=receiver,
                           my_teaching=my_teaching,
                           their_teaching=their_teaching)


# ══════════════════════════════════════════════════════════════════
# Accept a request
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/accept/<int:req_id>', methods=['POST'])
@login_required
def accept(req_id):
    """Only the receiver can accept a pending request."""
    req = ExchangeRequest.query.get_or_404(req_id)

    # Authorization
    if req.receiver_id != current_user.id:
        flash('You are not authorized to accept this request.', 'danger')
        return redirect(url_for('exchanges.index'))

    # State validation
    if not _can_transition(req.status, 'accepted'):
        flash(f'This request is currently {req.status} and cannot be accepted.',
              'warning')
        return redirect(url_for('exchanges.index', tab='pending'))

    req.status     = 'accepted'
    req.updated_at = _NOW()

    push_notification(
        req.sender_id,
        title=f'{current_user.full_name} accepted your exchange request!',
        body='You can now start messaging to arrange your skill exchange.',
        link=url_for('messages.conversation', user_id=current_user.id),
        icon='fa-check-circle',
        notif_type='exchange_accepted',
    )
    db.session.commit()

    flash('Request accepted! You can now message each other.', 'success')
    return redirect(url_for('exchanges.index', tab='accepted'))


# ══════════════════════════════════════════════════════════════════
# Reject a request
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/reject/<int:req_id>', methods=['POST'])
@login_required
def reject(req_id):
    """Only the receiver can reject a pending request."""
    req = ExchangeRequest.query.get_or_404(req_id)

    # Authorization
    if req.receiver_id != current_user.id:
        flash('You are not authorized to reject this request.', 'danger')
        return redirect(url_for('exchanges.index'))

    # State validation
    if not _can_transition(req.status, 'rejected'):
        flash(f'This request is currently {req.status} and cannot be rejected.',
              'warning')
        return redirect(url_for('exchanges.index', tab='pending'))

    req.status     = 'rejected'
    req.updated_at = _NOW()

    push_notification(
        req.sender_id,
        title=f'{current_user.full_name} declined your exchange request.',
        body='Your exchange request was declined.',
        link=url_for('exchanges.index'),
        icon='fa-times-circle',
        notif_type='exchange_rejected',
    )
    db.session.commit()

    flash('Request rejected.', 'info')
    return redirect(url_for('exchanges.index', tab='pending'))


# ══════════════════════════════════════════════════════════════════
# Cancel a request (by sender)
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/cancel/<int:req_id>', methods=['POST'])
@login_required
def cancel(req_id):
    """Only the sender can cancel their own pending or accepted request."""
    req = ExchangeRequest.query.get_or_404(req_id)

    # Authorization
    if req.sender_id != current_user.id:
        flash('You can only cancel your own requests.', 'danger')
        return redirect(url_for('exchanges.index'))

    # State validation
    if not _can_transition(req.status, 'cancelled'):
        flash(f'This request is currently {req.status} and cannot be cancelled.',
              'warning')
        return redirect(url_for('exchanges.index'))

    req.status     = 'cancelled'
    req.updated_at = _NOW()

    push_notification(
        req.receiver_id,
        title=f'{current_user.full_name} cancelled their exchange request.',
        body='The request has been withdrawn.',
        link=url_for('exchanges.index'),
        icon='fa-times-circle',
        notif_type='exchange_request',
    )
    db.session.commit()

    flash('Request cancelled.', 'info')
    return redirect(url_for('exchanges.index'))


# ══════════════════════════════════════════════════════════════════
# Mark as completed (by either party)
# ══════════════════════════════════════════════════════════════════

@exchanges_bp.route('/complete/<int:req_id>', methods=['POST'])
@login_required
def complete(req_id):
    """Either party can mark an accepted request as completed."""
    req = ExchangeRequest.query.get_or_404(req_id)

    # Authorization — either sender or receiver
    if current_user.id not in (req.sender_id, req.receiver_id):
        flash('You are not authorized to complete this request.', 'danger')
        return redirect(url_for('exchanges.index'))

    # State validation
    if not _can_transition(req.status, 'completed'):
        flash(f'This request is currently {req.status} and cannot be '
              f'marked as completed.', 'warning')
        return redirect(url_for('exchanges.index'))

    req.status     = 'completed'
    req.updated_at = _NOW()

    # Notify the other party
    other_id = (req.receiver_id if req.sender_id == current_user.id
                 else req.sender_id)
    push_notification(
        other_id,
        title='Exchange marked as completed!',
        body='Please leave a review for your partner.',
        link=url_for('reviews.add', exchange_id=req_id),
        icon='fa-star',
        notif_type='review',
    )
    db.session.commit()

    flash('Exchange marked as completed! Consider leaving a review.', 'success')
    return redirect(url_for('reviews.add', exchange_id=req_id))
