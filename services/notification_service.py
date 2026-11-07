"""
app/services/notification_service.py
====================================
Centralised notification creation that:
  - Writes a Notification row to SQLite
  - Emits a real-time SocketIO event to the user's room
  - Prevents exact duplicate notifications for the same event

Usage:
    from app.services.notification_service import push_notification
    push_notification(user_id, title='...', body='...', link='/...',
                       icon='fa-handshake', notif_type='exchange_request')
"""

from datetime import datetime, timezone, timedelta
from ..models import db, Notification

_IST = timedelta(hours=5, minutes=30)


def _fmt_ist(dt) -> str:
    if not dt:
        return ''
    return (dt + _IST).strftime('%b %d, %I:%M %p').lstrip('0')


def push_notification(
    user_id: int,
    *,
    title: str,
    body: str = '',
    link: str = '',
    icon: str = 'fa-bell',
    notif_type: str = 'general',
    dedup_key: str | None = None,
) -> Notification | None:
    """
    Create a notification and emit it in real time.

    Parameters
    ----------
    user_id     : the recipient's user id
    title       : short heading (shown in bell dropdown + browser notif)
    body        : longer text (shown in dropdown, NOT in browser notif for messages)
    link        : URL path to navigate to when clicked
    icon        : Font Awesome icon class (e.g. 'fa-envelope', 'fa-handshake')
    notif_type  : category — message / exchange_request / exchange_accepted /
                  exchange_rejected / review / call_audio / call_video / general
    dedup_key   : if provided, skip creation if an unread notification with
                  the same notif_type AND dedup_key body already exists

    Returns the created Notification object, or None if deduplicated.
    """
    # ── Duplicate prevention ─────────────────────────────────
    if dedup_key:
        existing = Notification.query.filter_by(
            user_id=user_id,
            notif_type=notif_type,
            is_read=False,
        ).filter(Notification.body == dedup_key).first()
        if existing:
            return None

    # ── Create DB row ─────────────────────────────────────────
    n = Notification(
        user_id=user_id,
        title=title,
        body=body or '',
        link=link or '',
        icon=icon,
        notif_type=notif_type,
        is_read=False,
    )
    db.session.add(n)
    db.session.commit()

    # ── Emit real-time event ──────────────────────────────────
    try:
        from flask_socketio import emit
        emit('notification', {
            'id':          n.id,
            'title':       n.title,
            'body':        n.body if n.notif_type != 'message' else '',
            'link':        n.link,
            'icon':        n.icon,
            'notif_type':  n.notif_type,
            'time':        _fmt_ist(n.created_at),
        }, room=f'user_{user_id}', namespace='/')
    except Exception:
        pass  # SocketIO may not be available (e.g. in CLI context)

    return n


def mark_read(notif_id: int, user_id: int) -> bool:
    """Mark a single notification as read. Returns True if found + updated."""
    n = db.session.get(Notification, notif_id)
    if not n or n.user_id != user_id:
        return False
    n.is_read = True
    db.session.commit()
    return True


def mark_all_read(user_id: int) -> int:
    """Mark all of a user's notifications as read. Returns count."""
    count = Notification.query.filter_by(
        user_id=user_id, is_read=False
    ).update({'is_read': True})
    db.session.commit()
    return count


def clear_all(user_id: int) -> int:
    """Delete all notifications for a user. Returns count."""
    count = Notification.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return count


def get_unread_count(user_id: int) -> int:
    """Return the number of unread notifications."""
    return Notification.query.filter_by(
        user_id=user_id, is_read=False
    ).count()


def get_recent(user_id: int, limit: int = 8) -> list[dict]:
    """Return recent notifications as dicts for the dropdown."""
    notifs = (Notification.query
              .filter_by(user_id=user_id)
              .order_by(Notification.created_at.desc())
              .limit(limit).all())
    result = []
    for n in notifs:
        result.append({
            'id':         n.id,
            'title':      n.title,
            'body':       n.body,
            'link':       n.link,
            'icon':       n.icon,
            'notif_type': n.notif_type,
            'is_read':    n.is_read,
            'time':       _fmt_ist(n.created_at),
        })
    return result
