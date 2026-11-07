"""
dashboard/routes.py
===================
Student dashboard with analytics.

Stat cards (all computed from live DB records):
  - Total connections (accepted + completed exchanges)
  - Active exchanges (status = accepted)
  - Completed exchanges (status = completed)
  - Pending requests (incoming, status = pending)
  - Average rating (from reviews received)

Chart.js endpoints (all return real DB data via AJAX):
  - /dashboard/chart-data              → popular teaching skills (bar)
  - /dashboard/chart-data/learning     → most requested learning skills (bar)
  - /dashboard/chart-data/monthly      → monthly exchange activity (line)
  - /dashboard/chart-data/progress     → learning progress (doughnut)
"""

from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from ..models import (db, User, Skill, ExchangeRequest, Notification,
                      Review, user_teaching_skills, user_learning_skills)
from ..services.matching_service import find_matches
from sqlalchemy import func, extract

dashboard_bp = Blueprint('dashboard', __name__)


# ══════════════════════════════════════════════════════════════════
# Main dashboard page
# ══════════════════════════════════════════════════════════════════

@dashboard_bp.route('/')
@login_required
def home():
    """Render the dashboard with stat cards, charts, matches, and feeds."""

    uid = current_user.id

    # ── Stat cards (all from real DB queries) ───────────────────
    total_connections = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == uid) |
         (ExchangeRequest.receiver_id == uid)),
        ExchangeRequest.status.in_(['accepted', 'completed'])
    ).count()

    active_exchanges = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == uid) |
         (ExchangeRequest.receiver_id == uid)),
        ExchangeRequest.status == 'accepted'
    ).count()

    completed_exchanges = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == uid) |
         (ExchangeRequest.receiver_id == uid)),
        ExchangeRequest.status == 'completed'
    ).count()

    pending_requests = ExchangeRequest.query.filter_by(
        receiver_id=uid, status='pending'
    ).count()

    avg_rating = current_user.avg_rating

    # ── Top matches (top 4) ──────────────────────────────────────
    candidates = (User.query
                   .filter(User.id != uid,
                           User.is_active == True,
                           User.is_admin == False)
                   .all())
    all_matches = find_matches(current_user, candidates)
    top_matches = all_matches[:4]

    # ── Recent notifications ─────────────────────────────────────
    notifications = (Notification.query
                     .filter_by(user_id=uid)
                     .order_by(Notification.created_at.desc())
                     .limit(5).all())

    # ── Recent activity ─────────────────────────────────────────
    recent_requests = (ExchangeRequest.query
                       .filter((ExchangeRequest.sender_id == uid) |
                               (ExchangeRequest.receiver_id == uid))
                       .order_by(ExchangeRequest.updated_at.desc())
                       .limit(5).all())

    return render_template(
        'dashboard/home.html',
        total_connections=total_connections,
        active_exchanges=active_exchanges,
        completed_exchanges=completed_exchanges,
        pending_requests=pending_requests,
        avg_rating=avg_rating,
        top_matches=top_matches,
        notifications=notifications,
        recent_requests=recent_requests,
    )


# ══════════════════════════════════════════════════════════════════
# AJAX: Chart data endpoints
# ══════════════════════════════════════════════════════════════════

@dashboard_bp.route('/chart-data')
@login_required
def chart_data():
    """Popular teaching skills — top 8 most-taught skills on the platform."""
    rows = (db.session.query(
                Skill.name,
                func.count(user_teaching_skills.c.user_id).label('cnt')
            )
            .join(user_teaching_skills, Skill.id == user_teaching_skills.c.skill_id)
            .group_by(Skill.name)
            .order_by(func.count(user_teaching_skills.c.user_id).desc())
            .limit(8).all())

    return jsonify({
        'labels': [r[0] for r in rows],
        'data':   [r[1] for r in rows],
    })


@dashboard_bp.route('/chart-data/learning')
@login_required
def chart_data_learning():
    """Most requested learning skills — top 8 skills students want to learn."""
    rows = (db.session.query(
                Skill.name,
                func.count(user_learning_skills.c.user_id).label('cnt')
            )
            .join(user_learning_skills, Skill.id == user_learning_skills.c.skill_id)
            .group_by(Skill.name)
            .order_by(func.count(user_learning_skills.c.user_id).desc())
            .limit(8).all())

    return jsonify({
        'labels': [r[0] for r in rows],
        'data':   [r[1] for r in rows],
    })


@dashboard_bp.route('/chart-data/monthly')
@login_required
def chart_data_monthly():
    """
    Monthly exchange activity — exchanges created per month for the
    last 6 months.  Counts all exchanges on the platform (not just
    the current user's) to show platform-wide trends.
    """
    # Build last 6 months labels
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    months: list[dict] = []
    for i in range(5, -1, -1):
        d = now - timedelta(days=30 * i)
        months.append({
            'label': d.strftime('%b'),
            'year':  d.year,
            'month': d.month,
        })

    # Query exchange counts grouped by year + month
    rows = (db.session.query(
                extract('year',  ExchangeRequest.created_at).label('yr'),
                extract('month', ExchangeRequest.created_at).label('mo'),
                func.count(ExchangeRequest.id).label('cnt')
            )
            .group_by(extract('year', ExchangeRequest.created_at),
                      extract('month', ExchangeRequest.created_at))
            .all())

    # Build a lookup dict {(year, month): count}
    lookup = {(int(r.yr), int(r.mo)): int(r.cnt) for r in rows}

    # Map to the last-6-months labels
    data = []
    for m in months:
        data.append(lookup.get((m['year'], m['month']), 0))

    return jsonify({
        'labels': [m['label'] for m in months],
        'data':   data,
    })


@dashboard_bp.route('/chart-data/progress')
@login_required
def chart_data_progress():
    """
    Student learning progress — doughnut chart showing:
      - Skills learned (completed exchanges where user was the learner)
      - Skills in progress (accepted exchanges where user is learner)
      - Skills not started (learning list minus those in exchanges)
    """
    uid = current_user.id

    # Skills the user wants to learn
    learning_skill_ids = {s.id for s in current_user.learning_skills}
    total_learning = len(learning_skill_ids)

    # Skills where the user is the receiver (learner) in a completed exchange
    completed_skill_ids = set()
    completed_reqs = ExchangeRequest.query.filter(
        ExchangeRequest.receiver_id == uid,
        ExchangeRequest.status == 'completed',
    ).all()
    for req in completed_reqs:
        if req.skill_requested_id:
            completed_skill_ids.add(req.skill_requested_id)

    # Skills where the user is the receiver in an accepted exchange
    in_progress_skill_ids = set()
    accepted_reqs = ExchangeRequest.query.filter(
        ExchangeRequest.receiver_id == uid,
        ExchangeRequest.status == 'accepted',
    ).all()
    for req in accepted_reqs:
        if req.skill_requested_id:
            in_progress_skill_ids.add(req.skill_requested_id)

    learned     = len(completed_skill_ids)
    in_progress = len(in_progress_skill_ids - completed_skill_ids)
    not_started = total_learning - learned - in_progress
    if not_started < 0:
        not_started = 0

    return jsonify({
        'labels': ['Learned', 'In Progress', 'Not Started'],
        'data':   [learned, in_progress, not_started],
        'total':  total_learning,
    })


# ══════════════════════════════════════════════════════════════════
# Mark notification as read
# ══════════════════════════════════════════════════════════════════

@dashboard_bp.route('/notification/<int:nid>/read', methods=['POST'])
@login_required
def mark_notification_read(nid):
    n = Notification.query.get_or_404(nid)
    if n.user_id == current_user.id:
        n.is_read = True
        db.session.commit()
    return ('', 204)

# ══════════════════════════════════════════════════════════════════
# Notification API — AJAX endpoints for the bell dropdown
# ══════════════════════════════════════════════════════════════════

from ..services.notification_service import (
    get_recent, get_unread_count, mark_read,
    mark_all_read, clear_all,
)


@dashboard_bp.route('/notifications/api')
@login_required
def notifications_api():
    """Return recent notifications + unread count as JSON."""
    return jsonify({
        'notifications': get_recent(current_user.id, limit=10),
        'unread_count':  get_unread_count(current_user.id),
    })


@dashboard_bp.route('/notifications/<int:nid>/read', methods=['POST'])
@login_required
def api_mark_read(nid):
    """Mark a single notification as read."""
    ok = mark_read(nid, current_user.id)
    return jsonify({'ok': ok, 'unread_count': get_unread_count(current_user.id)})


@dashboard_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def api_mark_all_read():
    """Mark all notifications as read."""
    count = mark_all_read(current_user.id)
    return jsonify({'ok': True, 'marked': count, 'unread_count': 0})


@dashboard_bp.route('/notifications/clear', methods=['POST'])
@login_required
def api_clear_all():
    """Delete all notifications."""
    count = clear_all(current_user.id)
    return jsonify({'ok': True, 'cleared': count, 'unread_count': 0})
