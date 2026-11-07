"""
matching/routes.py
==================
Smart Skill Matching — web layer.

Delegates all algorithm logic to the matching_service module and
handles only HTTP concerns: parsing query params, rendering the
template, and passing data to the view.
"""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from ..models import User, Skill
from ..services.matching_service import find_matches

matching_bp = Blueprint('matching', __name__)

# Re-export the skill categories list from the skills blueprint
# so the template can render category filter pills.
from ..skills.routes import SKILL_CATEGORIES


@matching_bp.route('/')
@login_required
def matches():
    """
    GET /match/
    Query params:
        min_score   — int (0, 50, 75, 90)  minimum match percentage
        category    — str                  skill category filter
        q           — str                  search by name or college
    """

    # ── Parse query parameters ──────────────────────────────
    min_score   = request.args.get('min_score', 0, type=int)
    category    = request.args.get('category', '').strip()
    search      = request.args.get('q', '').strip()

    # ── Check if the user has any skills ─────────────────────
    has_skills = (current_user.teaching_skills.count() > 0 or
                  current_user.learning_skills.count() > 0)

    if not has_skills:
        return render_template('matching/matches.html',
                               results=[],
                               no_skills=True,
                               categories=SKILL_CATEGORIES,
                               min_score=min_score,
                               category=category,
                               search_query=search)

    # ── Fetch candidate students from the DB ─────────────────
    # Exclude: self, inactive, admin accounts
    candidates = (User.query
                   .filter(User.id != current_user.id,
                           User.is_active == True,
                           User.is_admin == False)
                   .all())

    # ── Run the matching service ─────────────────────────────
    results = find_matches(
        current_user,
        candidates,
        min_score=min_score,
        category_filter=category,
        search_query=search,
    )

    return render_template('matching/matches.html',
                           results=results,
                           no_skills=False,
                           categories=SKILL_CATEGORIES,
                           min_score=min_score,
                           category=category,
                           search_query=search)
