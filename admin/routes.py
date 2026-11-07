"""
admin/routes.py
================
Admin panel for SkillSwap platform administrators.

Features:
  - Dedicated admin login page at /admin/login
  - Secure admin-only authorization (admin_required decorator)
  - Platform statistics dashboard with Chart.js
  - View / search / filter registered students (by name, email, college, branch)
  - Activate / deactivate user accounts (with safety checks)
  - Monitor all exchange requests with status filter
  - View and manage reported users
  - Flag users as reported / clear reports
  - Manage platform skills (delete)
  - AJAX stats data endpoint for charts

Security:
  - Every route is protected by @login_required + @admin_required
  - Admin login checks is_admin flag before granting access
  - Admins cannot deactivate themselves
  - Admins cannot toggle other admin accounts
  - Normal students are redirected away from all admin routes
  - Privilege escalation via registration/profile edit is impossible
    (is_admin is only set by the create-admin CLI command)
"""

from functools import wraps
from datetime import datetime, timezone
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, abort)
from flask_login import login_user, logout_user, login_required, current_user
from ..models import db, User, Skill, ExchangeRequest, Review
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__)


# ══════════════════════════════════════════════════════════════════
# Admin-only decorator
# ══════════════════════════════════════════════════════════════════

def admin_required(f):
    """
    Decorator that checks the current user is an authenticated admin.
    Normal students are redirected to the admin login page.
    Applied on EVERY admin route — never rely on UI-only hiding.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required. This area is restricted to platform '
                  'administrators.', 'danger')
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    """
    Decorator that checks the current user has the super_admin role.
    Regular admins are redirected to the admin dashboard.
    Only Varsha Patil (role='super_admin') can access these routes.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            flash('Super admin access required. '
                  'This action is restricted to the platform owner.', 'danger')
            return redirect(url_for('admin.index'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════
# Admin Login — separate from student login
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Dedicated admin login page at /admin/login.
    Only users with is_admin=True are granted access.
    Regular students who try to log in here are blocked even if
    their password is correct.
    """
    # Already logged in as admin → go to admin dashboard
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin.index'))

    # Logged in as student → force them out first
    if current_user.is_authenticated and not current_user.is_admin:
        flash('You do not have admin privileges. '
              'Please log out of your student account first.', 'warning')
        return redirect(url_for('dashboard.home'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter your admin email and password.', 'warning')
            return render_template('admin/login.html')

        user = User.query.filter_by(email=email).first()

        # ── Verify: must exist, password correct, AND be an admin ─
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'danger')
            return render_template('admin/login.html', email=email)

        if not user.is_admin:
            # Student trying to use admin login — give no extra information
            flash('Invalid email or password.', 'danger')
            return render_template('admin/login.html', email=email)

        if not user.is_active:
            flash('This admin account is deactivated.', 'danger')
            return render_template('admin/login.html', email=email)

        # ── Successful admin login ─────────────────────────────
        login_user(user, remember=False)
        user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

        flash(f'Welcome back, {user.full_name.split()[0]}! '
              'You are signed in as Administrator.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/login.html', email='')


@admin_bp.route('/logout', methods=['POST'])
@login_required
@admin_required
def logout():
    """Sign the admin out and return to admin login."""
    name = current_user.full_name.split()[0]
    logout_user()
    flash(f'Admin session ended. Goodbye, {name}!', 'info')
    return redirect(url_for('admin.login'))


# ══════════════════════════════════════════════════════════════════
# Admin dashboard — platform statistics
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/')
@login_required
@admin_required
def index():
    """Admin dashboard with platform-wide statistics and charts."""
    total_users     = User.query.filter_by(is_admin=False).count()
    active_users    = User.query.filter_by(is_admin=False, is_active=True).count()
    total_skills    = Skill.query.count()
    total_exchanges = ExchangeRequest.query.count()
    completed_ex    = ExchangeRequest.query.filter_by(status='completed').count()
    pending_ex      = ExchangeRequest.query.filter_by(status='pending').count()
    reported_users  = User.query.filter_by(is_reported=True).count()
    total_reviews   = Review.query.count()

    recent_users = (User.query
                    .filter_by(is_admin=False)
                    .order_by(User.created_at.desc())
                    .limit(10).all())

    return render_template('admin/index.html',
                           total_users=total_users,
                           active_users=active_users,
                           total_skills=total_skills,
                           total_exchanges=total_exchanges,
                           completed_ex=completed_ex,
                           pending_ex=pending_ex,
                           reported_users=reported_users,
                           total_reviews=total_reviews,
                           recent_users=recent_users,
                           is_super_admin=current_user.is_super_admin)


# ══════════════════════════════════════════════════════════════════
# User management — list, search, filter, activate/deactivate
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """
    Paginated list of all non-admin students.
    Query params: ?q=<search> &status=<active|inactive|reported>
                  &college=<college> &branch=<branch>
    """
    page    = request.args.get('page', 1, type=int)
    search  = request.args.get('q', '').strip()
    status  = request.args.get('status', '').strip()
    college = request.args.get('college', '').strip()
    branch  = request.args.get('branch', '').strip()

    query = User.query.filter_by(is_admin=False)

    # Search by name or email
    if search:
        query = query.filter(
            User.full_name.ilike(f'%{search}%') |
            User.email.ilike(f'%{search}%')
        )

    # College filter
    if college:
        query = query.filter(User.college.ilike(f'%{college}%'))

    # Branch filter
    if branch:
        query = query.filter(User.branch.ilike(f'%{branch}%'))

    # Status filter
    if status == 'active':
        query = query.filter_by(is_active=True)
    elif status == 'inactive':
        query = query.filter_by(is_active=False)
    elif status == 'reported':
        query = query.filter_by(is_reported=True)

    users_pg = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    # Distinct college + branch lists for filter dropdowns
    all_colleges = [r[0] for r in
                    db.session.query(User.college).filter(User.is_admin == False,
                    User.college.isnot(None)).distinct().order_by(User.college).all()]
    all_branches = [r[0] for r in
                    db.session.query(User.branch).filter(User.is_admin == False,
                    User.branch.isnot(None)).distinct().order_by(User.branch).all()]

    return render_template('admin/users.html',
                           users_pg=users_pg,
                           search=search,
                           status_filter=status,
                           college_filter=college,
                           branch_filter=branch,
                           all_colleges=all_colleges,
                           all_branches=all_branches)


# ── Toggle user active/inactive ──────────────────────────────────

@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    """Activate or deactivate a student account with safety checks."""
    user = User.query.get_or_404(user_id)

    # Safety: prevent self-deactivation
    if user.id == current_user.id:
        flash('You cannot deactivate your own admin account.', 'warning')
        return redirect(url_for('admin.users'))

    # Safety: prevent toggling other admin accounts
    if user.is_admin:
        flash('Admin accounts cannot be toggled from this panel.', 'warning')
        return redirect(url_for('admin.users'))

    user.is_active = not user.is_active
    db.session.commit()
    state = 'activated' if user.is_active else 'deactivated'
    flash(f'User {user.full_name} has been {state}.', 'success')
    return redirect(url_for('admin.users',
                             q=request.form.get('q', ''),
                             status=request.form.get('status', ''),
                             college=request.form.get('college', ''),
                             branch=request.form.get('branch', '')))


# ── Report a user (flag) ─────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/report', methods=['POST'])
@login_required
@admin_required
def report_user(user_id):
    """Flag a user as reported."""
    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash('Admin accounts cannot be reported.', 'warning')
        return redirect(url_for('admin.users'))

    user.is_reported = True
    db.session.commit()
    flash(f'User {user.full_name} has been flagged for review.', 'warning')
    return redirect(url_for('admin.reported'))


# ══════════════════════════════════════════════════════════════════
# Skill management
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/skills')
@login_required
@admin_required
def skills():
    """List all platform skills for management."""
    all_skills = Skill.query.order_by(Skill.category, Skill.name).all()
    return render_template('admin/skills.html', skills=all_skills)


@admin_bp.route('/skills/delete/<int:skill_id>', methods=['POST'])
@login_required
@admin_required
def delete_skill(skill_id):
    """Delete a skill from the platform."""
    skill = Skill.query.get_or_404(skill_id)
    db.session.delete(skill)
    db.session.commit()
    flash(f'Skill "{skill.name}" deleted.', 'info')
    return redirect(url_for('admin.skills'))


# ══════════════════════════════════════════════════════════════════
# Exchange monitoring
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/exchanges')
@login_required
@admin_required
def exchanges():
    """Paginated list of all exchange requests with optional status filter."""
    page   = request.args.get('page', 1, type=int)
    status = request.args.get('status', '').strip()

    query = ExchangeRequest.query
    if status:
        query = query.filter_by(status=status)

    exchanges_pg = query.order_by(ExchangeRequest.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/exchanges.html',
                           exchanges_pg=exchanges_pg, status=status)


# ══════════════════════════════════════════════════════════════════
# Reported users management
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/reported')
@login_required
@admin_required
def reported():
    """View all reported users for admin review."""
    reported_users = User.query.filter_by(is_reported=True).all()
    return render_template('admin/reported.html', reported_users=reported_users)


@admin_bp.route('/users/<int:user_id>/clear-report', methods=['POST'])
@login_required
@admin_required
def clear_report(user_id):
    """Clear the reported flag on a user."""
    user = User.query.get_or_404(user_id)
    user.is_reported = False
    db.session.commit()
    flash(f'Report cleared for {user.full_name}.', 'success')
    return redirect(url_for('admin.reported'))


# ══════════════════════════════════════════════════════════════════
# AJAX: stats data for charts
# ══════════════════════════════════════════════════════════════════

@admin_bp.route('/stats-data')
@login_required
@admin_required
def stats_data():
    """Return JSON chart data: top skills + exchange status distribution."""
    from ..models import user_teaching_skills
    skill_rows = (db.session.query(
                      Skill.name,
                      func.count(user_teaching_skills.c.user_id).label('cnt')
                  )
                  .join(user_teaching_skills,
                        Skill.id == user_teaching_skills.c.skill_id)
                  .group_by(Skill.name)
                  .order_by(func.count(user_teaching_skills.c.user_id).desc())
                  .limit(8).all())

    status_rows = (db.session.query(
                       ExchangeRequest.status,
                       func.count(ExchangeRequest.id)
                   )
                   .group_by(ExchangeRequest.status).all())

    return jsonify({
        'skills':   {'labels': [r[0] for r in skill_rows],
                      'data':   [r[1] for r in skill_rows]},
        'statuses': {'labels': [r[0] for r in status_rows],
                      'data':   [r[1] for r in status_rows]},
    })
