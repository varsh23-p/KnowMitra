"""
reviews/routes.py
=================
Ratings and reviews module for completed skill exchanges.

Features:
  - Rate completed exchanges (1–5 stars)
  - Written feedback (optional, max 500 chars)
  - Duplicate review prevention (one review per exchange per reviewer)
  - Average rating calculation (via User.avg_rating property)
  - Rating breakdown bars (5★ to 1★) on the reviews list page
  - Notification sent to the reviewed student
  - Access control: only exchange participants can review
  - State validation: only completed exchanges can be reviewed
"""

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request)
from flask_login import login_required, current_user
from ..models import db, Review, ExchangeRequest, User, Notification
from ..services.notification_service import push_notification

reviews_bp = Blueprint('reviews', __name__)

MAX_FEEDBACK_LENGTH = 500


def _notify(user_id: int, title: str, body: str, link: str) -> None:
    """Create an in-app notification for the reviewed user."""
    n = Notification(user_id=user_id, title=title, body=body,
                     link=link, icon='fa-star')
    db.session.add(n)


# ══════════════════════════════════════════════════════════════════
# Add a review
# ══════════════════════════════════════════════════════════════════

@reviews_bp.route('/add/<int:exchange_id>', methods=['GET', 'POST'])
@login_required
def add(exchange_id):
    """GET → show review form.  POST → validate and save the review."""
    exchange = ExchangeRequest.query.get_or_404(exchange_id)

    # ── Authorization: only participants can review ──────────────
    if current_user.id not in (exchange.sender_id, exchange.receiver_id):
        flash('You are not authorized to review this exchange.', 'danger')
        return redirect(url_for('exchanges.index'))

    # ── State validation: only completed exchanges ───────────────
    if exchange.status != 'completed':
        flash('You can only review completed exchanges.', 'warning')
        return redirect(url_for('exchanges.index'))

    # Determine who is being reviewed (the other party)
    reviewee_id = (exchange.receiver_id
                   if exchange.sender_id == current_user.id
                   else exchange.sender_id)

    # ── Duplicate prevention: one review per exchange per reviewer ─
    existing = Review.query.filter_by(
        reviewer_id=current_user.id,
        exchange_id=exchange_id
    ).first()
    if existing:
        flash('You have already reviewed this exchange.', 'warning')
        return redirect(url_for('profile.view', user_id=reviewee_id))

    # ── Handle POST ─────────────────────────────────────────────
    if request.method == 'POST':
        rating   = request.form.get('rating', type=int)
        feedback = request.form.get('feedback', '').strip()

        errors: list[str] = []

        # Validate rating
        if not rating or rating < 1 or rating > 5:
            errors.append('Please select a rating between 1 and 5.')

        # Validate feedback length
        if len(feedback) > MAX_FEEDBACK_LENGTH:
            errors.append(f'Feedback cannot exceed {MAX_FEEDBACK_LENGTH} characters.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('reviews.add', exchange_id=exchange_id))

        # ── Create the review ────────────────────────────────────
        review = Review(
            reviewer_id=current_user.id,
            reviewee_id=reviewee_id,
            exchange_id=exchange_id,
            rating=rating,
            feedback=feedback or None,
        )
        db.session.add(review)
        push_notification(
            reviewee_id,
            title=f'{current_user.full_name} left you a {rating}\u2605 review!',
            body=feedback[:120] if feedback else '',
            link=url_for('profile.view', user_id=reviewee_id),
            icon='fa-star',
            notif_type='review',
        )
        db.session.commit()

        flash('Review submitted successfully!', 'success')
        return redirect(url_for('profile.view', user_id=reviewee_id))

    # ── GET: render the form ─────────────────────────────────────
    reviewee = db.session.get(User, reviewee_id)
    return render_template('reviews/add.html',
                           exchange=exchange,
                           reviewee=reviewee)


# ══════════════════════════════════════════════════════════════════
# View all reviews for a user
# ══════════════════════════════════════════════════════════════════

@reviews_bp.route('/user/<int:user_id>')
@login_required
def user_reviews(user_id):
    """Render the reviews list page with rating breakdown."""
    student = User.query.get_or_404(user_id)
    reviews = (Review.query
               .filter_by(reviewee_id=user_id)
               .order_by(Review.created_at.desc()).all())
    return render_template('reviews/list.html', student=student, reviews=reviews)
