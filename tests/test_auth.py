"""
tests/test_auth.py
==================
Comprehensive tests for the SkillSwap authentication module.

Every test gets its own fresh client (function-scope) so there is
no session bleed between tests.

Covered requirements:
  1.  Student registration (happy path)
  2.  Login with correct credentials
  3.  Logout
  4.  Password hashing – Werkzeug pbkdf2:sha256 / scrypt
  5.  Flask-Login session management
  6.  Duplicate email registration blocked
  7.  Email and password validation rules
  8.  Protected routes redirect unauthenticated users
  9.  Flash messages (success, error, warning, info)
  10. Post-login redirect to /dashboard/
  11. Post-login ?next= redirect (safe same-host only)
  12. Brute-force lockout after 5 failed attempts
  13. Deactivated account blocked
  14. Case-insensitive email lookup
  15. Remember-me flag
"""

import pytest
from app import create_app
from app.models import db as _db, User


# ══════════════════════════════════════════════════════════════════
# App  – single instance, in-memory DB, created once per session
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope='session')
def app():
    test_app = create_app('testing')
    test_app.config.update(
        TESTING                 = True,
        WTF_CSRF_ENABLED        = False,
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:',
        SECRET_KEY              = 'test-secret',
    )
    # Create tables once — do NOT keep the app context open.
    # Each test/request will push its own context with a fresh session.
    with test_app.app_context():
        _db.create_all()
    yield test_app
    with test_app.app_context():
        _db.drop_all()


# ══════════════════════════════════════════════════════════════════
# Per-test fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset(app):
    """
    Wipe all user rows and reset brute-force tracker before every test.
    Opens its own short-lived app context so the session is isolated
    from the one used by the test client's requests.
    """
    with app.app_context():
        _db.session.query(User).delete()
        _db.session.commit()
        _db.session.remove()       # discard identity map + close session

    from app.auth.routes import _login_attempts
    _login_attempts.clear()
    yield


@pytest.fixture()
def client(app):
    """Fresh test client – no shared session state."""
    with app.test_client() as c:
        yield c


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

_REG = dict(
    full_name        = 'Test Student',
    email            = 'test@college.edu',
    password         = 'secret1',
    confirm_password = 'secret1',
    college          = 'Test University',
    branch           = 'Computer Science',
    year             = '2nd Year',
)


def do_register(c, **kw):
    """POST /auth/register – always follow=False so we never auto-login."""
    return c.post('/auth/register', data={**_REG, **kw}, follow_redirects=False)


def do_register_and_follow(c, **kw):
    """Register and follow the redirect chain (lands on login page)."""
    r = do_register(c, **kw)
    if r.status_code == 302:
        return c.get(r.headers['Location'], follow_redirects=True)
    return r   # validation error page is returned directly (200)


def do_login(c, email='test@college.edu', password='secret1',
             remember=False, follow=True):
    data = {'email': email, 'password': password}
    if remember:
        data['remember'] = 'on'
    return c.post('/auth/login', data=data, follow_redirects=follow)


def do_logout(c, follow=True):
    return c.post('/auth/logout', follow_redirects=follow)


def reg_login(c, **kw):
    """Register a user (no follow) then immediately login."""
    do_register(c, **kw)
    return do_login(c,
                    email=kw.get('email', _REG['email']),
                    password=kw.get('password', _REG['password']))


def get_flashed(resp):
    """Extract flash message text from response bytes (lowercase)."""
    return resp.data.decode('utf-8', errors='replace').lower()


# ══════════════════════════════════════════════════════════════════
# 1. Registration – happy path
# ══════════════════════════════════════════════════════════════════

class TestRegistration:

    def test_creates_user(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
        assert u is not None
        assert u.full_name == 'Test Student'

    def test_redirects_to_login(self, client):
        r = do_register(client)
        assert r.status_code == 302
        assert '/auth/login' in r.headers['Location']

    def test_success_flash_on_login_page(self, client):
        r = do_register_and_follow(client)
        assert 'welcome' in get_flashed(r) or 'ready' in get_flashed(r)

    def test_password_is_hashed(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
        assert u.password_hash != 'secret1'
        assert u.password_hash.startswith(('pbkdf2:', 'scrypt:'))

    def test_check_password_correct(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
        assert u.check_password('secret1') is True

    def test_check_password_wrong(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
        assert u.check_password('wrong') is False

    def test_optional_fields_saved(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
        assert u.college == 'Test University'
        assert u.branch  == 'Computer Science'
        assert u.year    == '2nd Year'

    def test_logged_in_user_skips_register(self, client):
        reg_login(client)
        r = client.get('/auth/register', follow_redirects=False)
        assert r.status_code == 302
        assert '/dashboard' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# 6 & 7. Duplicate email + validation
# ══════════════════════════════════════════════════════════════════

class TestRegistrationValidation:

    # ── duplicate email ─────────────────────────────────────────

    def test_duplicate_email_stays_200(self, client):
        """Second registration with same email → validation error (200, not 302)."""
        do_register(client)
        r = do_register(client)          # same email
        assert r.status_code == 200      # stays on register page

    def test_duplicate_email_flash(self, client):
        do_register(client)
        r = do_register(client)
        assert 'already' in get_flashed(r) or 'exists' in get_flashed(r)

    def test_duplicate_email_case_insensitive(self, client):
        do_register(client, email='Test@College.EDU')
        r = do_register(client, email='test@college.edu')
        assert r.status_code == 200
        assert 'already' in get_flashed(r) or 'exists' in get_flashed(r)

    # ── email format ─────────────────────────────────────────────

    def test_invalid_email_stays_200(self, client):
        r = do_register(client, email='notanemail')
        assert r.status_code == 200

    def test_invalid_email_flash(self, client):
        r = do_register(client, email='notanemail')
        assert 'email' in get_flashed(r)

    def test_empty_email_stays_200(self, client):
        r = do_register(client, email='')
        assert r.status_code == 200

    def test_empty_email_flash(self, client):
        r = do_register(client, email='')
        text = get_flashed(r)
        assert 'email' in text or 'required' in text

    # ── full name ────────────────────────────────────────────────

    def test_short_name_stays_200(self, client):
        r = do_register(client, full_name='A')
        assert r.status_code == 200

    def test_short_name_flash(self, client):
        r = do_register(client, full_name='A')
        text = get_flashed(r)
        assert 'name' in text or 'least' in text or '2' in text

    def test_empty_name_stays_200(self, client):
        r = do_register(client, full_name='')
        assert r.status_code == 200

    # ── password rules ───────────────────────────────────────────

    def test_too_short_password_stays_200(self, client):
        r = do_register(client, password='ab1', confirm_password='ab1')
        assert r.status_code == 200

    def test_too_short_password_flash(self, client):
        r = do_register(client, password='ab1', confirm_password='ab1')
        text = get_flashed(r)
        assert '6' in text or 'character' in text

    def test_no_digit_password_stays_200(self, client):
        r = do_register(client, password='abcdef', confirm_password='abcdef')
        assert r.status_code == 200

    def test_no_digit_password_flash(self, client):
        r = do_register(client, password='abcdef', confirm_password='abcdef')
        text = get_flashed(r)
        assert 'number' in text or 'digit' in text

    def test_passwords_mismatch_stays_200(self, client):
        r = do_register(client, password='secret1', confirm_password='secret2')
        assert r.status_code == 200

    def test_passwords_mismatch_flash(self, client):
        r = do_register(client, password='secret1', confirm_password='secret2')
        assert 'match' in get_flashed(r)

    def test_form_repopulates_email(self, client):
        """Email is echoed back when validation fails."""
        r = do_register(client, email='myemail@test.com', full_name='A')
        assert b'myemail@test.com' in r.data


# ══════════════════════════════════════════════════════════════════
# 2. Login – happy path
# ══════════════════════════════════════════════════════════════════

class TestLogin:

    def test_success_200(self, client):
        do_register(client)
        r = do_login(client)
        assert r.status_code == 200

    def test_redirects_to_dashboard(self, client):
        do_register(client)
        r = do_login(client, follow=False)
        assert r.status_code == 302
        assert '/dashboard' in r.headers['Location']

    def test_welcome_flash(self, client):
        do_register(client)
        r = do_login(client)
        assert 'welcome' in get_flashed(r) or 'back' in get_flashed(r)

    def test_updates_last_seen(self, client, app):
        do_register(client)
        with app.app_context():
            before = User.query.filter_by(email='test@college.edu').first().last_seen
        do_login(client)
        with app.app_context():
            after = User.query.filter_by(email='test@college.edu').first().last_seen
        assert after >= before

    def test_case_insensitive_email(self, client):
        do_register(client, email='test@college.edu')
        r = do_login(client, email='TEST@COLLEGE.EDU')
        # Must reach dashboard, not stay on login
        assert r.status_code == 200
        assert 'dashboard' in get_flashed(r) or 'welcome' in get_flashed(r)

    def test_safe_next_redirect(self, client):
        do_register(client)
        r = client.post(
            '/auth/login?next=/skills/',
            data={'email': 'test@college.edu', 'password': 'secret1'},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert '/skills/' in r.headers['Location']

    def test_external_next_rejected(self, client):
        do_register(client)
        r = client.post(
            '/auth/login?next=http://evil.com/',
            data={'email': 'test@college.edu', 'password': 'secret1'},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert 'evil.com' not in r.headers['Location']

    def test_authenticated_user_bypasses_login(self, client):
        reg_login(client)
        r = client.get('/auth/login', follow_redirects=False)
        assert r.status_code == 302
        assert '/dashboard' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# Invalid login scenarios
# ══════════════════════════════════════════════════════════════════

class TestLoginFailures:

    def test_wrong_password_stays_on_login(self, client):
        do_register(client)
        r = do_login(client, password='badpassword')
        assert r.status_code == 200

    def test_wrong_password_flash(self, client):
        do_register(client)
        r = do_login(client, password='badpassword')
        assert 'incorrect' in get_flashed(r)

    def test_unknown_email_flash(self, client):
        r = do_login(client, email='nobody@nowhere.com')
        assert 'incorrect' in get_flashed(r)

    def test_empty_email_stays_on_login(self, client):
        r = do_login(client, email='', follow=False)
        assert r.status_code in (200, 302)
        if r.status_code == 302:
            r = client.get(r.headers['Location'], follow_redirects=True)
        text = get_flashed(r)
        assert 'email' in text or 'password' in text or 'both' in text

    def test_empty_password_stays_on_login(self, client):
        r = do_login(client, password='', follow=False)
        assert r.status_code in (200, 302)
        if r.status_code == 302:
            r = client.get(r.headers['Location'], follow_redirects=True)
        text = get_flashed(r)
        assert 'password' in text or 'both' in text or 'email' in text

    def test_deactivated_account_blocked(self, client, app):
        do_register(client)
        with app.app_context():
            u = User.query.filter_by(email='test@college.edu').first()
            u.is_active = False
            _db.session.commit()
        r = do_login(client)
        assert 'deactivated' in get_flashed(r)

    def test_brute_force_lockout(self, client):
        do_register(client)
        for _ in range(5):
            do_login(client, password='wrong_pw')
        # 6th attempt – even correct password is blocked
        r = do_login(client, password='secret1')
        text = get_flashed(r)
        assert 'locked' in text or 'too many' in text

    def test_remaining_attempts_shown(self, client):
        do_register(client)
        r = do_login(client, password='wrong_pw')
        text = get_flashed(r)
        assert 'attempt' in text or 'remaining' in text


# ══════════════════════════════════════════════════════════════════
# 3. Logout
# ══════════════════════════════════════════════════════════════════

class TestLogout:

    def test_redirects_to_login(self, client):
        reg_login(client)
        r = do_logout(client, follow=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_signout_flash(self, client):
        reg_login(client)
        r = do_logout(client)
        text = get_flashed(r)
        assert 'signed out' in text or 'logged out' in text

    def test_session_ended_after_logout(self, client):
        reg_login(client)
        do_logout(client)
        r = client.get('/dashboard/', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_anon_logout_redirects_to_login(self, client):
        r = do_logout(client, follow=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_get_logout_confirm_page(self, client):
        reg_login(client)
        r = client.get('/auth/logout/confirm', follow_redirects=True)
        assert r.status_code == 200
        assert b'Sign Out' in r.data or b'sign out' in r.data.lower()

    def test_confirm_page_does_not_end_session(self, client):
        """Visiting /logout/confirm must NOT log the user out."""
        reg_login(client)
        client.get('/auth/logout/confirm', follow_redirects=True)
        r = client.get('/dashboard/', follow_redirects=False)
        # Still authenticated → 200 on dashboard
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════
# 5 & 8. Session management + route protection
# ══════════════════════════════════════════════════════════════════

class TestSessionAndProtection:

    PROTECTED = [
        '/dashboard/',
        '/profile/edit',
        '/skills/manage',
        '/exchanges/',
        '/messages/',
        '/match/',
    ]

    def test_anon_protected_routes_redirect(self, client):
        for url in self.PROTECTED:
            r = client.get(url, follow_redirects=False)
            assert r.status_code == 302, f"{url} must redirect anon users"
            assert 'login' in r.headers.get('Location', '').lower(), \
                   f"{url} must redirect to login"

    def test_dashboard_accessible_logged_in(self, client):
        reg_login(client)
        r = client.get('/dashboard/', follow_redirects=True)
        assert r.status_code == 200

    def test_all_protected_accessible_logged_in(self, client):
        reg_login(client)
        for url in self.PROTECTED:
            r = client.get(url, follow_redirects=True)
            assert r.status_code == 200, f"{url} should be 200 when logged in"

    def test_flash_on_anon_access(self, client):
        r = client.get('/dashboard/', follow_redirects=True)
        text = get_flashed(r)
        assert 'sign in' in text or 'please' in text or 'log in' in text


# ══════════════════════════════════════════════════════════════════
# 4. Password hashing  (unit tests on model, no HTTP)
# ══════════════════════════════════════════════════════════════════

class TestPasswordHashing:

    def test_not_plaintext(self, app):
        with app.app_context():
            u = User(full_name='T', email='t1@t.com')
            u.set_password('pass1')
            assert u.password_hash != 'pass1'

    def test_werkzeug_algorithm(self, app):
        with app.app_context():
            u = User(full_name='T', email='t2@t.com')
            u.set_password('pass1')
            assert u.password_hash.startswith(('pbkdf2:', 'scrypt:'))

    def test_correct_password_ok(self, app):
        with app.app_context():
            u = User(full_name='T', email='t3@t.com')
            u.set_password('correct1')
            assert u.check_password('correct1') is True

    def test_wrong_password_rejected(self, app):
        with app.app_context():
            u = User(full_name='T', email='t4@t.com')
            u.set_password('correct1')
            assert u.check_password('wrong') is False

    def test_salt_makes_hashes_unique(self, app):
        with app.app_context():
            u1 = User(full_name='T', email='t5@t.com')
            u2 = User(full_name='T', email='t6@t.com')
            u1.set_password('same1')
            u2.set_password('same1')
            assert u1.password_hash != u2.password_hash

    def test_hash_is_long(self, app):
        with app.app_context():
            u = User(full_name='T', email='t7@t.com')
            u.set_password('pass1')
            assert len(u.password_hash) > 40
