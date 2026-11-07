"""
skills/routes.py
================
Skill management module — add, edit, delete skills and manage the
teaching / learning lists for the current user.

Key features:
  - Browse the full skill library (filterable by category)
  - Manage my skills (teaching + learning lists)
  - Add a new skill to the platform (with category + description)
  - Add an existing skill to your teaching list (with proficiency)
  - Add an existing skill to your learning goals
  - Edit the proficiency level of a teaching skill
  - Remove a skill from your teaching or learning list
  - AJAX endpoint for live skill search (autocomplete)
  - Full server-side validation on every action
"""

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify)
from flask_login import login_required, current_user
from ..models import db, Skill, user_teaching_skills, user_learning_skills
from sqlalchemy import text

skills_bp = Blueprint('skills', __name__)

# ── Predefined categories with Font Awesome icons ───────────────
SKILL_CATEGORIES = [
    ('Programming',     'fa-code'),
    ('Web Development', 'fa-globe'),
    ('Data Science',    'fa-chart-bar'),
    ('Design',          'fa-paint-brush'),
    ('Music',           'fa-music'),
    ('Photography',     'fa-camera'),
    ('Language',        'fa-language'),
    ('Writing',         'fa-pen'),
    ('Mathematics',     'fa-calculator'),
    ('Science',         'fa-flask'),
    ('Business',        'fa-briefcase'),
    ('Art & Craft',     'fa-palette'),
    ('Sports',          'fa-running'),
    ('Cooking',         'fa-utensils'),
    ('Other',           'fa-star'),
]

PROFICIENCY_LEVELS = ['Beginner', 'Intermediate', 'Expert']

# Quick lookup sets for validation
_VALID_CATEGORIES  = {cat for cat, _ in SKILL_CATEGORIES}
_VALID_PROFICIENCY = set(PROFICIENCY_LEVELS)

# Field length limits
MAX_SKILL_NAME = 100
MAX_SKILL_DESC = 300


# ══════════════════════════════════════════════════════════════════
# Skill Library  —  browse all platform skills
# ══════════════════════════════════════════════════════════════════

@skills_bp.route('/')
@login_required
def index():
    """Paginated list of all skills, optionally filtered by category."""
    category  = request.args.get('category', '').strip()
    query     = Skill.query

    if category and category in _VALID_CATEGORIES:
        query = query.filter_by(category=category)

    all_skills = query.order_by(Skill.category, Skill.name).all()

    my_teaching_ids = {s.id for s in current_user.teaching_skills}
    my_learning_ids = {s.id for s in current_user.learning_skills}

    return render_template('skills/index.html',
                           all_skills=all_skills,
                           categories=SKILL_CATEGORIES,
                           selected_category=category,
                           my_teaching_ids=my_teaching_ids,
                           my_learning_ids=my_learning_ids)


# ══════════════════════════════════════════════════════════════════
# Manage My Skills
# ══════════════════════════════════════════════════════════════════

@skills_bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage():
    """
    GET  → show the management page with current skills + add panels.
    POST → dispatch based on the hidden 'action' field.
    """

    if request.method == 'POST':
        action = request.form.get('action', '')

        # ── Dispatch ───────────────────────────────────────────
        handler = {
            'create_skill':      _handle_create_skill,
            'add_teaching':      _handle_add_teaching,
            'add_learning':      _handle_add_learning,
            'remove_teaching':   _handle_remove_teaching,
            'remove_learning':   _handle_remove_learning,
            'edit_proficiency':  _handle_edit_proficiency,
        }.get(action)

        if handler:
            return handler()
        # Unknown action — ignore gracefully
        flash('Unknown action.', 'warning')
        return redirect(url_for('skills.manage'))

    # ── GET: assemble the page ─────────────────────────────────
    all_skills = Skill.query.order_by(Skill.category, Skill.name).all()

    # Fetch proficiency data for the current user's teaching skills
    rows = db.session.execute(
        text('SELECT skill_id, proficiency FROM user_teaching_skills WHERE user_id=:u'),
        {'u': current_user.id}
    ).fetchall()
    teaching_proficiency = {r[0]: r[1] for r in rows}

    return render_template('skills/manage.html',
                           all_skills=all_skills,
                           categories=SKILL_CATEGORIES,
                           proficiency_levels=PROFICIENCY_LEVELS,
                           teaching_skills=current_user.teaching_skills.all(),
                           learning_skills=current_user.learning_skills.all(),
                           teaching_proficiency=teaching_proficiency)


# ══════════════════════════════════════════════════════════════════
# POST handlers  (private functions)
# ══════════════════════════════════════════════════════════════════

def _handle_create_skill():
    """Create a brand-new skill and add it to the platform library."""
    name        = request.form.get('skill_name', '').strip()
    category    = request.form.get('category', 'Other')
    description = request.form.get('description', '').strip()

    errors: list[str] = []

    # Validate name
    if not name:
        errors.append('Skill name is required.')
    elif len(name) < 2:
        errors.append('Skill name must be at least 2 characters.')
    elif len(name) > MAX_SKILL_NAME:
        errors.append(f'Skill name cannot exceed {MAX_SKILL_NAME} characters.')

    # Validate category
    if category not in _VALID_CATEGORIES:
        errors.append('Please select a valid category.')

    # Validate description length
    if len(description) > MAX_SKILL_DESC:
        errors.append(f'Description cannot exceed {MAX_SKILL_DESC} characters.')

    # Check for duplicate (case-insensitive)
    if name and Skill.query.filter(Skill.name.ilike(name)).first():
        existing = Skill.query.filter(Skill.name.ilike(name)).first()
        flash(f'A skill named "{existing.name}" already exists in the library.', 'warning')
        return redirect(url_for('skills.manage'))

    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('skills.manage'))

    # Determine the icon for this category
    icon = next((ic for cat, ic in SKILL_CATEGORIES if cat == category), 'fa-star')

    skill = Skill(name=name, category=category,
                  description=description or None, icon=icon)
    db.session.add(skill)
    db.session.commit()

    flash(f'Skill "{name}" added to the platform!', 'success')
    return redirect(url_for('skills.manage'))


def _handle_add_teaching():
    """Add an existing skill to the current user's teaching list."""
    skill_id    = request.form.get('skill_id', type=int)
    proficiency = request.form.get('proficiency', 'Intermediate')

    skill = db.session.get(Skill, skill_id) if skill_id else None
    if not skill:
        flash('Please select a valid skill.', 'danger')
        return redirect(url_for('skills.manage'))

    if proficiency not in _VALID_PROFICIENCY:
        flash('Please select a valid proficiency level.', 'danger')
        return redirect(url_for('skills.manage'))

    # Check for duplicate
    already = db.session.execute(
        text('SELECT 1 FROM user_teaching_skills WHERE user_id=:u AND skill_id=:s'),
        {'u': current_user.id, 's': skill_id}
    ).fetchone()

    if already:
        flash(f'You already teach "{skill.name}".', 'warning')
    else:
        db.session.execute(
            text('INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                 'VALUES (:u, :s, :p)'),
            {'u': current_user.id, 's': skill_id, 'p': proficiency}
        )
        db.session.commit()
        flash(f'"{skill.name}" added to your teaching skills!', 'success')

    return redirect(url_for('skills.manage'))


def _handle_add_learning():
    """Add an existing skill to the current user's learning goals."""
    skill_id = request.form.get('skill_id', type=int)

    skill = db.session.get(Skill, skill_id) if skill_id else None
    if not skill:
        flash('Please select a valid skill.', 'danger')
        return redirect(url_for('skills.manage'))

    # Check for duplicate
    already = db.session.execute(
        text('SELECT 1 FROM user_learning_skills WHERE user_id=:u AND skill_id=:s'),
        {'u': current_user.id, 's': skill_id}
    ).fetchone()

    if already:
        flash(f'"{skill.name}" is already in your learning list.', 'warning')
    else:
        db.session.execute(
            text('INSERT INTO user_learning_skills (user_id, skill_id) '
                 'VALUES (:u, :s)'),
            {'u': current_user.id, 's': skill_id}
        )
        db.session.commit()
        flash(f'"{skill.name}" added to your learning goals!', 'success')

    return redirect(url_for('skills.manage'))


def _handle_remove_teaching():
    """Remove a skill from the current user's teaching list."""
    skill_id = request.form.get('skill_id', type=int)

    if not skill_id:
        flash('Invalid request.', 'danger')
        return redirect(url_for('skills.manage'))

    db.session.execute(
        text('DELETE FROM user_teaching_skills WHERE user_id=:u AND skill_id=:s'),
        {'u': current_user.id, 's': skill_id}
    )
    db.session.commit()
    flash('Teaching skill removed.', 'info')
    return redirect(url_for('skills.manage'))


def _handle_remove_learning():
    """Remove a skill from the current user's learning goals."""
    skill_id = request.form.get('skill_id', type=int)

    if not skill_id:
        flash('Invalid request.', 'danger')
        return redirect(url_for('skills.manage'))

    db.session.execute(
        text('DELETE FROM user_learning_skills WHERE user_id=:u AND skill_id=:s'),
        {'u': current_user.id, 's': skill_id}
    )
    db.session.commit()
    flash('Learning goal removed.', 'info')
    return redirect(url_for('skills.manage'))


def _handle_edit_proficiency():
    """Update the proficiency level for an existing teaching skill."""
    skill_id    = request.form.get('skill_id', type=int)
    proficiency = request.form.get('proficiency', 'Intermediate')

    skill = db.session.get(Skill, skill_id) if skill_id else None
    if not skill:
        flash('Please select a valid skill.', 'danger')
        return redirect(url_for('skills.manage'))

    if proficiency not in _VALID_PROFICIENCY:
        flash('Please select a valid proficiency level.', 'danger')
        return redirect(url_for('skills.manage'))

    # Verify the skill is actually in the user's teaching list
    existing = db.session.execute(
        text('SELECT 1 FROM user_teaching_skills WHERE user_id=:u AND skill_id=:s'),
        {'u': current_user.id, 's': skill_id}
    ).fetchone()

    if not existing:
        flash(f'You don\'t currently teach "{skill.name}".', 'warning')
        return redirect(url_for('skills.manage'))

    db.session.execute(
        text('UPDATE user_teaching_skills SET proficiency=:p '
             'WHERE user_id=:u AND skill_id=:s'),
        {'p': proficiency, 'u': current_user.id, 's': skill_id}
    )
    db.session.commit()
    flash(f'Proficiency for "{skill.name}" updated to {proficiency}.', 'success')
    return redirect(url_for('skills.manage'))


# ══════════════════════════════════════════════════════════════════
# AJAX: live skill search (autocomplete)
# ══════════════════════════════════════════════════════════════════

@skills_bp.route('/search')
@login_required
def search():
    """Return JSON array of skills matching the query string."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    results = (Skill.query
               .filter(Skill.name.ilike(f'%{q}%'))
               .order_by(Skill.name)
               .limit(10).all())
    return jsonify([{
        'id':       s.id,
        'name':     s.name,
        'category': s.category,
    } for s in results])
