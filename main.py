"""
main.py - Landing page and misc public routes.
"""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user
from .models import User, Skill, ExchangeRequest

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Public landing page."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    # Stats for landing page hero section
    total_students = User.query.filter_by(is_admin=False, is_active=True).count()
    total_skills   = Skill.query.count()
    total_exchanges = ExchangeRequest.query.filter_by(status='completed').count()

    # Sample skills for the landing page showcase
    popular_skills = Skill.query.limit(8).all()

    return render_template(
        'index.html',
        total_students=total_students,
        total_skills=total_skills,
        total_exchanges=total_exchanges,
        popular_skills=popular_skills
    )


@main_bp.route('/about')
def about():
    """Public About page — project info and creator profile."""
    return render_template('about.html')
