"""
app/cli.py
==========
Flask CLI commands for SkillSwap administrative tasks.

Available commands
------------------
  flask --app run create-admin
      Interactive: prompts for name, email, role, password.
      Creates a new admin OR updates an existing one.

  flask --app run create-super-admin
      Shortcut for Varsha Patil's super_admin account.
      Name and email are pre-filled; only password is prompted.

Security guarantees
-------------------
  - Passwords are NEVER stored in source code.
  - All passwords are collected at runtime via hidden prompts.
  - Passwords are hashed with Werkzeug (pbkdf2:sha256 + salt).
  - Students cannot promote themselves via registration or profile edit.
  - Only these CLI commands can set is_admin=True or role='super_admin'.
"""

import re
import click
from flask import Blueprint
from werkzeug.security import generate_password_hash

cli_bp = Blueprint('cli', __name__, cli_group=None)

_EMAIL_RE    = re.compile(r'^[\w\.\+\-]+@[\w\-]+\.[\w\.]{2,}$')
_VALID_ROLES = ('admin', 'super_admin')

# ─────────────────────────────────────────────────────────────────
_HEADER = '═' * 58
_DIVIDER = '─' * 58


def _check_password(pw: str) -> list[str]:
    """Return list of unmet requirements (empty = valid)."""
    issues = []
    if len(pw) < 8:
        issues.append('at least 8 characters')
    if not any(c.isdigit() for c in pw):
        issues.append('at least one number')
    if not any(c.isalpha() for c in pw):
        issues.append('at least one letter')
    return issues


def _prompt_password() -> str:
    """Loop until the user enters a valid, confirmed password."""
    while True:
        password = click.prompt('  Password', hide_input=True)
        issues = _check_password(password)
        if issues:
            click.echo(f'  ✗  Password must contain: {", ".join(issues)}.\n')
            continue
        confirm = click.prompt('  Confirm password', hide_input=True)
        if password != confirm:
            click.echo('  ✗  Passwords do not match. Try again.\n')
            continue
        return password


def _upsert_admin(full_name: str, email: str,
                  password: str, role: str) -> None:
    """
    Create or update an admin account.

    Rules:
      - If the email belongs to a STUDENT → blocked (no privilege escalation).
      - If the email belongs to an existing ADMIN → updates name, role,
        and optionally password (asks the operator).
      - If the email is new → creates a fresh admin account.

    No existing data is deleted. Student accounts are never touched.
    """
    from .models import db, User

    existing = User.query.filter_by(email=email).first()

    if existing:
        if not existing.is_admin:
            click.echo(
                '\n  ✗  That email belongs to a STUDENT account.\n'
                '     Admin accounts must use a separate email address.\n'
                '     No changes were made.\n'
            )
            return

        # Existing admin — show current state
        click.echo(f'\n  ℹ  Admin account already exists:')
        click.echo(f'     Name  : {existing.full_name}')
        click.echo(f'     Email : {existing.email}')
        click.echo(f'     Role  : {existing.role or "admin"} → will become {role}')
        click.echo(f'     Active: {existing.is_active}')

        update_pw = click.confirm(
            '\n  Update password as well?', default=False
        )
        if not click.confirm('  Apply these changes?', default=True):
            click.echo('\n  No changes made.\n')
            return

        existing.full_name = full_name
        existing.role      = role
        existing.is_admin  = True
        existing.is_active = True
        if update_pw:
            new_pw = _prompt_password()
            existing.password_hash = generate_password_hash(new_pw)

        db.session.commit()
        click.echo(f'\n{_DIVIDER}')
        click.echo(f'  ✓  Admin account updated.')
        _print_summary(full_name, email, role)
        return

    # Brand-new account
    admin = User(
        full_name  = full_name,
        email      = email,
        is_admin   = True,
        is_active  = True,
        role       = role,
        college    = 'SkillSwap Administration',
        experience = 'Expert',
    )
    admin.password_hash = generate_password_hash(password)

    try:
        db.session.add(admin)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        click.echo(f'\n  ✗  Database error: {exc}\n')
        return

    click.echo(f'\n{_DIVIDER}')
    click.echo(f'  ✓  Admin account created successfully.')
    _print_summary(full_name, email, role)


def _print_summary(full_name: str, email: str, role: str) -> None:
    click.echo(f'     Name  : {full_name}')
    click.echo(f'     Email : {email}')
    click.echo(f'     Role  : {role}')
    click.echo(f'{_DIVIDER}')
    click.echo(f'\n  Login at:  http://localhost:5000/admin/login\n')


# ═════════════════════════════════════════════════════════════════
# Command 1: create-admin   (fully interactive)
# ═════════════════════════════════════════════════════════════════

@cli_bp.cli.command('create-admin')
def create_admin():
    """
    Interactively create or update an admin / super_admin account.

    Prompts for:
      1. Full name
      2. Email address
      3. Role (admin or super_admin)
      4. Password (hidden, confirmed)

    Safe to run more than once on the same email — will offer to
    update the existing account instead of creating a duplicate.
    """
    click.echo(f'\n{_HEADER}')
    click.echo('  SkillSwap  —  Admin Account Manager')
    click.echo(f'{_HEADER}\n')

    # ── Full name ──────────────────────────────────────────────
    while True:
        full_name = click.prompt('  Full name').strip()
        if len(full_name) >= 2:
            break
        click.echo('  ✗  Name must be at least 2 characters.\n')

    # ── Email ──────────────────────────────────────────────────
    while True:
        email = click.prompt('  Email address').strip().lower()
        if _EMAIL_RE.match(email):
            break
        click.echo('  ✗  Invalid email format. Try again.\n')

    # ── Role ───────────────────────────────────────────────────
    click.echo('\n  Select role:')
    click.echo('    [1] admin        — standard admin')
    click.echo('    [2] super_admin  — full super-admin privileges\n')
    while True:
        choice = click.prompt('  Role', default='1').strip()
        if choice in ('1', 'admin'):
            role = 'admin'
            break
        elif choice in ('2', 'super_admin'):
            role = 'super_admin'
            break
        click.echo('  ✗  Enter 1 or 2.\n')

    # ── Password (only needed for new accounts; upsert asks separately) ─
    from .models import User
    existing = User.query.filter_by(email=email).first()
    password = None
    if not existing:
        click.echo()
        password = _prompt_password()

    _upsert_admin(full_name, email, password or '', role)


# ═════════════════════════════════════════════════════════════════
# Command 2: create-super-admin   (Varsha Patil shortcut)
# ═════════════════════════════════════════════════════════════════

@cli_bp.cli.command('create-super-admin')
def create_super_admin():
    """
    Create or update Varsha Patil's super_admin account.

    Name and email are pre-filled:
      Full Name : Varsha Patil
      Email     : varsha.patil23@skillswap.com
      Role      : super_admin

    Only the password is prompted (hidden, confirmed).
    Safe to run more than once — will offer to update if the
    account already exists.
    """
    FULL_NAME = 'Varsha Patil'
    EMAIL     = 'varsha.patil23@skillswap.com'
    ROLE      = 'super_admin'

    click.echo(f'\n{_HEADER}')
    click.echo('  SkillSwap  —  Create Super Admin Account')
    click.echo(f'{_HEADER}')
    click.echo(f'\n  Name  : {FULL_NAME}')
    click.echo(f'  Email : {EMAIL}')
    click.echo(f'  Role  : {ROLE}\n')

    from .models import User
    existing = User.query.filter_by(email=EMAIL).first()

    if existing:
        if not existing.is_admin:
            click.echo(
                '  ✗  This email is already used by a student account.\n'
                '     No changes made.\n'
            )
            return

        click.echo('  ℹ  Super admin account already exists.')
        click.echo(f'     Current role  : {existing.role or "admin"}')
        click.echo(f'     Current active: {existing.is_active}')

        if not click.confirm('\n  Update role to super_admin and reset password?',
                             default=False):
            click.echo('\n  No changes made.\n')
            return

        new_pw = _prompt_password()
        existing.role          = ROLE
        existing.is_admin      = True
        existing.is_active     = True
        existing.full_name     = FULL_NAME
        existing.password_hash = generate_password_hash(new_pw)

        from .models import db
        db.session.commit()
        click.echo(f'\n{_DIVIDER}')
        click.echo('  ✓  Super admin account updated.')
        _print_summary(FULL_NAME, EMAIL, ROLE)
        return

    # New account — prompt only for password
    password = _prompt_password()
    _upsert_admin(FULL_NAME, EMAIL, password, ROLE)
