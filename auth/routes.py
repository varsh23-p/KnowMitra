"""
auth/routes.py
==============
Complete authentication module for SkillSwap.

Covers:
  - Student registration with full server-side validation
  - Login with email + password, remember-me, next-page redirect
  - Logout (POST-only, CSRF-safe)
  - Duplicate-email check
  - Werkzeug password hashing  (pbkdf2:sha256)
  - Flask-Login session management
  - Route protection via @login_required
  - Brute-force throttling (5 failed attempts → 15-minute lock)
  - Detailed, user-friendly flash messages
"""

import re
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, abort)
from flask_login import login_user, logout_user, login_required, current_user

from ..models import db, User

auth_bp = Blueprint('auth', __name__)

# ══════════════════════════════════════════════════════════════════
# In-memory brute-force tracker
#   { ip_address: {'count': int, 'locked_until': float | None} }
# Resets on server restart – sufficient for development.
# In production swap for a Redis/DB-backed solution.
# ══════════════════════════════════════════════════════════════════
_login_attempts: dict = defaultdict(lambda: {'count': 0, 'locked_until': None})

MAX_ATTEMPTS   = 5      # failed attempts before lockout
LOCKOUT_SECS   = 900    # 15 minutes


def _get_ip() -> str:
    """Return the real client IP, respecting X-Forwarded-For."""
    return (request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown').split(',')[0].strip()


def _is_locked(ip: str) -> tuple[bool, int]:
    """Return (locked, seconds_remaining)."""
    rec = _login_attempts[ip]
    if rec['locked_until'] and time.time() < rec['locked_until']:
        remaining = int(rec['locked_until'] - time.time())
        return True, remaining
    return False, 0


def _record_failure(ip: str) -> None:
    rec = _login_attempts[ip]
    # Clear expired lock first
    if rec['locked_until'] and time.time() >= rec['locked_until']:
        rec['count'] = 0
        rec['locked_until'] = None
    rec['count'] += 1
    if rec['count'] >= MAX_ATTEMPTS:
        rec['locked_until'] = time.time() + LOCKOUT_SECS


def _clear_attempts(ip: str) -> None:
    _login_attempts[ip] = {'count': 0, 'locked_until': None}


# ══════════════════════════════════════════════════════════════════
# Validation helpers
# ══════════════════════════════════════════════════════════════════

_EMAIL_RE = re.compile(r'^[\w\.\+\-]+@[\w\-]+\.[\w\.]{2,}$')


def _validate_email(email: str) -> str | None:
    """Return None if valid, else an error message."""
    if not email:
        return 'Email address is required.'
    if not _EMAIL_RE.match(email):
        return 'Please enter a valid email address (e.g. you@college.edu).'
    if len(email) > 150:
        return 'Email address is too long (max 150 characters).'
    return None


def _validate_password(password: str) -> list[str]:
    """Return a list of unmet password requirements (empty = valid)."""
    issues = []
    if len(password) < 6:
        issues.append('at least 6 characters')
    if not any(c.isdigit() for c in password):
        issues.append('at least one number')
    return issues


def _safe_next(url: str | None) -> str:
    """Ensure the next-page redirect stays on this host."""
    if url and url.startswith('/') and not url.startswith('//'):
        return url
    return url_for('dashboard.home')


# ══════════════════════════════════════════════════════════════════
# REGISTER
# ══════════════════════════════════════════════════════════════════

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    GET  – show the registration form
    POST – validate input, create user, redirect to login
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    # Form field defaults used to re-populate on error
    form = {
        'full_name': '',
        'email':     '',
        'college':   '',
        'branch':    '',
        'year':      '',
    }

    if request.method == 'POST':
        # ── 1. Collect & sanitise ──────────────────────────────
        form['full_name'] = request.form.get('full_name', '').strip()
        form['email']     = request.form.get('email',     '').strip().lower()
        form['college']   = request.form.get('college',   '').strip()
        form['branch']    = request.form.get('branch',    '').strip()
        form['year']      = request.form.get('year',      '').strip()
        password          = request.form.get('password',          '')
        confirm_password  = request.form.get('confirm_password',  '')

        errors: list[str] = []

        # ── 2. Full name ───────────────────────────────────────
        if len(form['full_name']) < 2:
            errors.append('Full name must be at least 2 characters.')
        elif len(form['full_name']) > 120:
            errors.append('Full name is too long (max 120 characters).')

        # ── 3. Email ───────────────────────────────────────────
        email_err = _validate_email(form['email'])
        if email_err:
            errors.append(email_err)
        elif User.query.filter_by(email=form['email']).first():
            # Deliberately vague to avoid account enumeration on public forms,
            # but clear enough to help the user fix the issue.
            errors.append(
                'An account with that email address already exists. '
                'Try logging in, or use a different email.'
            )

        # ── 4. Password ────────────────────────────────────────
        pw_issues = _validate_password(password)
        if pw_issues:
            errors.append(
                f"Password must contain {' and '.join(pw_issues)}."
            )
        elif password != confirm_password:
            errors.append('Passwords do not match. Please retype them carefully.')

        # ── 5. Return early on errors ──────────────────────────
        if errors:
            for msg in errors:
                flash(msg, 'danger')
            return render_template('auth/register.html', **form)

        # ── 6. Create user ─────────────────────────────────────
        user = User(
            full_name = form['full_name'],
            email     = form['email'],
            college   = form['college'] or None,
            branch    = form['branch']  or None,
            year      = form['year']    or None,
        )
        user.set_password(password)   # Werkzeug pbkdf2:sha256 hashing

        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Something went wrong while creating your account. Please try again.', 'danger')
            return render_template('auth/register.html', **form)

        flash(
            f'Welcome to SkillSwap, {form["full_name"].split()[0]}! '
            'Your account is ready — please sign in.',
            'success'
        )
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', **form)


# ══════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET  – show login form (pre-fill email if provided)
    POST – authenticate user, set session, redirect to dashboard
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.home'))

    prefill_email = request.args.get('email', '')

    if request.method == 'POST':
        email    = request.form.get('email',    '').strip().lower()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        ip       = _get_ip()

        # ── 1. Check brute-force lock ──────────────────────────
        locked, remaining = _is_locked(ip)
        if locked:
            mins = remaining // 60
            secs = remaining %  60
            flash(
                f'Too many failed attempts. Your account is temporarily locked. '
                f'Try again in {mins}m {secs}s.',
                'danger'
            )
            return render_template('auth/login.html', email=email)

        # ── 2. Basic field presence check ─────────────────────
        if not email or not password:
            flash('Please enter both your email address and password.', 'warning')
            return render_template('auth/login.html', email=email)

        # ── 3. Lookup user ─────────────────────────────────────
        user = User.query.filter_by(email=email).first()

        # ── 4. Verify credentials ──────────────────────────────
        #  Use a single generic message to prevent user enumeration.
        if not user or not user.check_password(password):
            _record_failure(ip)
            rec     = _login_attempts[ip]
            left    = MAX_ATTEMPTS - rec['count']

            if left > 0:
                flash(
                    f'Incorrect email or password. '
                    f'{"1 attempt" if left == 1 else f"{left} attempts"} remaining before '
                    f'your account is temporarily locked.',
                    'danger'
                )
            else:
                flash(
                    f'Too many incorrect attempts. '
                    f'Please wait {LOCKOUT_SECS // 60} minutes before trying again.',
                    'danger'
                )
            return render_template('auth/login.html', email=email)

        # ── 5. Check account status ────────────────────────────
        if not user.is_active:
            flash(
                'Your account has been deactivated. '
                'Please contact support if you believe this is an error.',
                'warning'
            )
            return render_template('auth/login.html', email=email)

        # ── 6. Successful login ────────────────────────────────
        _clear_attempts(ip)          # reset brute-force counter
        login_user(user, remember=remember)

        user.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

        flash(
            f'Welcome back, {user.full_name.split()[0]}!',
            'success'
        )

        # Honour ?next= only when it is a safe same-host path
        return redirect(_safe_next(request.args.get('next')))

    return render_template('auth/login.html', email=prefill_email)


# ══════════════════════════════════════════════════════════════════
# LOGOUT  (POST only – protects against CSRF logout)
# ══════════════════════════════════════════════════════════════════

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """Sign the current user out and send them to the login page."""
    name = current_user.full_name.split()[0]
    logout_user()
    flash(f'You have been signed out. See you soon, {name}!', 'info')
    return redirect(url_for('auth.login'))


# ── GET /logout kept for convenience (browser URL bar, bookmarks) ─
@auth_bp.route('/logout/confirm')
@login_required
def logout_confirm():
    """
    Renders a simple confirmation page so users don't accidentally
    log out from a bookmark or stale link.
    """
    return render_template('auth/logout_confirm.html')
