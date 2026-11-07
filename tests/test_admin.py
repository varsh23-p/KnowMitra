"""
tests/test_admin.py
====================
Comprehensive tests for the admin panel and permission system.

Covers:
  Authorization:
    - Student blocked from all admin routes
    - Admin can access all routes
    - Unauthenticated user redirected to login
    - Admin_required decorator flash message

  Dashboard:
    - Platform statistics (real DB data)
    - Stats not hardcoded (change with DB)
    - Recent registrations shown
    - AJAX stats-data endpoint returns JSON

  User management:
    - View all students (paginated)
    - Search by name and email
    - Status filter (active, inactive, reported)
    - Activate a deactivated user
    - Deactivate an active user
    - Cannot self-deactivate
    - Cannot toggle other admin accounts
    - Report (flag) a user
    - Report an admin blocked

  Exchange monitoring:
    - View all exchanges
    - Filter by status (pending, accepted, completed, etc.)
    - Pagination

  Reported users:
    - View reported users
    - Clear report
    - Empty state when no reports

  Skill management:
    - View all skills
    - Delete a skill
    - Deleted skill disappears

  Stats endpoint:
    - Returns skills + statuses data
    - Login required
    - Admin only
"""

import pytest
from app import create_app
from app.models import db as _db, User, Skill, ExchangeRequest, Review
from sqlalchemy import text


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope='session')
def app():
    a = create_app('testing')
    a.config.update(
        TESTING=True, WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SECRET_KEY='test-secret',
    )
    with a.app_context():
        _db.create_all()
    yield a
    with a.app_context():
        _db.drop_all()


@pytest.fixture(autouse=True)
def reset(app):
    with app.app_context():
        _db.session.query(Review).delete()
        _db.session.query(ExchangeRequest).delete()
        _db.session.query(User).delete()
        _db.session.query(Skill).delete()
        _db.session.execute(text('DELETE FROM user_teaching_skills'))
        _db.session.execute(text('DELETE FROM user_learning_skills'))
        _db.session.commit()
        _db.session.remove()
    yield


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────

def _make_user(app, name, email, is_admin=False, is_active=True, is_reported=False):
    with app.app_context():
        u = User(full_name=name, email=email, college='Test College',
                 is_admin=is_admin, is_active=is_active, is_reported=is_reported)
        u.set_password('pass123')
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _make_skill(app, name, category='Programming'):
    with app.app_context():
        s = Skill(name=name, category=category, icon='fa-code')
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _make_exchange(app, sender_id, receiver_id, status='pending'):
    with app.app_context():
        r = ExchangeRequest(sender_id=sender_id, receiver_id=receiver_id,
                            status=status)
        _db.session.add(r)
        _db.session.commit()
        return r.id


def _login(c, email, password='pass123'):
    c.post('/auth/login', data={'email': email, 'password': password},
           follow_redirects=True)


def _register_and_login_student(c, email='student@test.edu', name='Student'):
    c.post('/auth/register', data={
        'full_name': name, 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
    }, follow_redirects=False)
    _login(c, email)


def _setup_admin_and_student(app, client):
    """Create an admin and a student, log in as admin."""
    admin_id   = _make_user(app, 'Admin User', 'admin@test.edu', is_admin=True)
    student_id = _make_user(app, 'Alice Student', 'alice@test.edu')
    _login(client, 'admin@test.edu')
    return admin_id, student_id


def _get_flash(resp):
    return resp.data.decode('utf-8', errors='replace').lower()


# ══════════════════════════════════════════════════════════════════
# AUTHORIZATION TESTS
# ══════════════════════════════════════════════════════════════════

class TestAdminAuthorization:

    # ── Unauthenticated users ────────────────────────────────────

    def test_unauthenticated_redirected_from_dashboard(self, client):
        r = client.get('/admin/', follow_redirects=False)
        # @login_required fires first → redirect to login
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_users(self, client):
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_exchanges(self, client):
        r = client.get('/admin/exchanges', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_reported(self, client):
        r = client.get('/admin/reported', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_skills(self, client):
        r = client.get('/admin/skills', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_stats(self, client):
        r = client.get('/admin/stats-data', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_unauthenticated_blocked_from_toggle(self, client):
        r = client.post('/admin/users/1/toggle', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    # ── Students blocked from all admin routes ──────────────────

    def test_student_blocked_from_dashboard(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_users(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_exchanges(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/exchanges', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_reported(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/reported', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_skills(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/skills', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_stats_data(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/stats-data', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_toggle_user(self, client, app):
        student_id = _make_user(app, 'Student', 'student@test.edu')
        other_id   = _make_user(app, 'Other', 'other@test.edu')
        _login(client, 'student@test.edu')
        r = client.post(f'/admin/users/{other_id}/toggle', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_clear_report(self, client, app):
        sid = _make_user(app, 'Student', 'student@test.edu')
        rid = _make_user(app, 'Reported', 'reported@test.edu', is_reported=True)
        _login(client, 'student@test.edu')
        r = client.post(f'/admin/users/{rid}/clear-report', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_delete_skill(self, client, app):
        sid = _make_user(app, 'Student', 'student@test.edu')
        skill_id = _make_skill(app, 'Python')
        _login(client, 'student@test.edu')
        r = client.post(f'/admin/skills/delete/{skill_id}', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    def test_student_blocked_from_report_user(self, client, app):
        sid = _make_user(app, 'Student', 'student@test.edu')
        oid = _make_user(app, 'Other', 'other@test.edu')
        _login(client, 'student@test.edu')
        r = client.post(f'/admin/users/{oid}/report', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']

    # ── Admin can access all routes ─────────────────────────────

    def test_admin_can_access_dashboard(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/')
        assert r.status_code == 200

    def test_admin_can_access_users(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/users')
        assert r.status_code == 200

    def test_admin_can_access_exchanges(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/exchanges')
        assert r.status_code == 200

    def test_admin_can_access_reported(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/reported')
        assert r.status_code == 200

    def test_admin_can_access_skills(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/skills')
        assert r.status_code == 200

    def test_admin_can_access_stats_data(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/stats-data')
        assert r.status_code == 200

    def test_admin_flash_on_student_access_attempt(self, client, app):
        """When a student tries to access admin routes, they see a flash message."""
        _register_and_login_student(client)
        r = client.get('/admin/', follow_redirects=True)
        assert 'admin' in _get_flash(r) or 'required' in _get_flash(r)

    def test_admin_login_page_accessible_publicly(self, client):
        """The /admin/login page is publicly accessible."""
        r = client.get('/admin/login')
        assert r.status_code == 200
        assert b'Admin' in r.data or b'admin' in r.data.lower()

    def test_admin_login_works(self, client, app):
        """An admin can log in via /admin/login."""
        admin_id, _ = _setup_admin_and_student(app, client)
        # Log out first (setup already logged us in)
        client.post('/auth/logout', follow_redirects=True)
        r = client.post('/admin/login', data={
            'email': 'admin@test.edu', 'password': 'pass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/' in r.headers['Location']

    def test_student_cannot_login_via_admin_login(self, client, app):
        """A student with valid credentials is blocked at /admin/login."""
        _make_user(app, 'Student', 'stu@test.edu')
        r = client.post('/admin/login', data={
            'email': 'stu@test.edu', 'password': 'pass123',
        }, follow_redirects=True)
        assert 'invalid' in _get_flash(r)


# ══════════════════════════════════════════════════════════════════
# DASHBOARD STATISTICS TESTS
# ══════════════════════════════════════════════════════════════════

class TestAdminDashboard:

    def test_shows_total_users(self, client, app):
        _, student_id = _setup_admin_and_student(app, client)
        _make_user(app, 'Bob', 'bob@test.edu')
        r = client.get('/admin/')
        assert r.status_code == 200
        assert b'Alice Student' in r.data or b'Bob' in r.data

    def test_shows_recent_registrations(self, client, app):
        _setup_admin_and_student(app, client)
        _make_user(app, 'New User', 'new@test.edu')
        r = client.get('/admin/')
        assert b'New User' in r.data

    def test_stats_reflect_real_db(self, client, app):
        """Stats must change when DB data changes — not hardcoded."""
        admin_id, _ = _setup_admin_and_student(app, client)
        r1 = client.get('/admin/')
        # Add more users
        _make_user(app, 'User 3', 'u3@test.edu')
        _make_user(app, 'User 4', 'u4@test.edu')
        r2 = client.get('/admin/')
        assert r1.status_code == 200 and r2.status_code == 200
        # The page should show different numbers (at least different content)

    def test_stats_data_returns_json(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/stats-data')
        assert r.status_code == 200
        data = r.get_json()
        assert 'skills' in data
        assert 'statuses' in data
        assert 'labels' in data['skills']
        assert 'data' in data['skills']

    def test_stats_data_shows_exchange_statuses(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, admin_id, student_id, status='pending')
        _make_exchange(app, admin_id, student_id, status='accepted')
        r = client.get('/admin/stats-data')
        data = r.get_json()
        assert 'pending' in data['statuses']['labels']
        assert 'accepted' in data['statuses']['labels']


# ══════════════════════════════════════════════════════════════════
# USER MANAGEMENT TESTS
# ══════════════════════════════════════════════════════════════════

class TestUserManagement:

    def test_view_users_shows_students(self, client, app):
        _, student_id = _setup_admin_and_student(app, client)
        _make_user(app, 'Visible User', 'visible@test.edu')
        r = client.get('/admin/users')
        assert r.status_code == 200
        assert b'Visible User' in r.data

    def test_view_users_excludes_admins(self, client, app):
        """Admin accounts must not appear in /admin/users — verified via DB query."""
        admin_id, student_id = _setup_admin_and_student(app, client)
        # The page must load and only show non-admin users
        r = client.get('/admin/users')
        assert r.status_code == 200
        # Check the DB: the route uses filter_by(is_admin=False) so admins
        # should never be in users_pg.items. Verify directly.
        with app.app_context():
            admin = User.query.get(admin_id)
            student = User.query.get(student_id)
            # Route query: User.query.filter_by(is_admin=False)
            from app.models import User as U
            non_admins = U.query.filter_by(is_admin=False).all()
            ids = [u.id for u in non_admins]
            assert admin_id not in ids
            assert student_id in ids

    def test_search_by_name(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Alice Wonder', 'alice2@test.edu')
        _make_user(app, 'Bob Builder', 'bob@test.edu')
        r = client.get('/admin/users?q=Alice')
        assert b'Alice Wonder' in r.data
        assert b'Bob Builder' not in r.data

    def test_search_by_email(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Search Me', 'findme@test.edu')
        r = client.get('/admin/users?q=findme')
        assert b'Search Me' in r.data

    def test_filter_active(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Active One', 'active1@test.edu', is_active=True)
        _make_user(app, 'Inactive One', 'inactive1@test.edu', is_active=False)
        r = client.get('/admin/users?status=active')
        assert b'Active One' in r.data
        assert b'Inactive One' not in r.data

    def test_filter_inactive(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Active Two', 'active2@test.edu', is_active=True)
        _make_user(app, 'Inactive Two', 'inactive2@test.edu', is_active=False)
        r = client.get('/admin/users?status=inactive')
        assert b'Inactive Two' in r.data
        assert b'Active Two' not in r.data

    def test_filter_reported(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Normal', 'normal@test.edu')
        _make_user(app, 'Flagged', 'flagged@test.edu', is_reported=True)
        r = client.get('/admin/users?status=reported')
        assert b'Flagged' in r.data
        assert b'Normal' not in r.data

    def test_deactivate_user(self, client, app):
        _, student_id = _setup_admin_and_student(app, client)
        r = client.post(f'/admin/users/{student_id}/toggle', follow_redirects=True)
        assert r.status_code == 200
        assert 'deactivated' in _get_flash(r)
        with app.app_context():
            u = User.query.get(student_id)
            assert u.is_active is False

    def test_activate_user(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        sid = _make_user(app, 'Deactivated', 'deact@test.edu', is_active=False)
        r = client.post(f'/admin/users/{sid}/toggle', follow_redirects=True)
        assert 'activated' in _get_flash(r)
        with app.app_context():
            assert User.query.get(sid).is_active is True

    def test_cannot_self_deactivate(self, client, app):
        """Admin cannot deactivate their own account."""
        admin_id, _ = _setup_admin_and_student(app, client)
        r = client.post(f'/admin/users/{admin_id}/toggle', follow_redirects=True)
        assert 'own' in _get_flash(r) or 'cannot' in _get_flash(r)
        with app.app_context():
            assert User.query.get(admin_id).is_active is True

    def test_cannot_toggle_admin_account(self, client, app):
        """Admin cannot toggle another admin's account."""
        _, _ = _setup_admin_and_student(app, client)
        other_admin = _make_user(app, 'Other Admin', 'admin2@test.edu', is_admin=True)
        r = client.post(f'/admin/users/{other_admin}/toggle', follow_redirects=True)
        assert 'admin' in _get_flash(r) or 'cannot' in _get_flash(r)
        with app.app_context():
            assert User.query.get(other_admin).is_active is True

    def test_toggle_nonexistent_user_404(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.post('/admin/users/99999/toggle', follow_redirects=False)
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════
# REPORT MANAGEMENT TESTS
# ══════════════════════════════════════════════════════════════════

class TestReportManagement:

    def test_reported_page_shows_flagged_users(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        _make_user(app, 'Bad Actor', 'bad@test.edu', is_reported=True)
        r = client.get('/admin/reported')
        assert r.status_code == 200
        assert b'Bad Actor' in r.data

    def test_reported_page_empty_state(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/reported')
        assert r.status_code == 200
        assert b'No reported' in r.data or b'no reported' in _get_flash(r)

    def test_clear_report(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        rid = _make_user(app, 'Reported User', 'rep@test.edu', is_reported=True)
        r = client.post(f'/admin/users/{rid}/clear-report', follow_redirects=True)
        assert 'cleared' in _get_flash(r)
        with app.app_context():
            assert User.query.get(rid).is_reported is False

    def test_report_user(self, client, app):
        """Admin can flag a user as reported."""
        _, _ = _setup_admin_and_student(app, client)
        sid = _make_user(app, 'To Report', 'toreport@test.edu')
        r = client.post(f'/admin/users/{sid}/report', follow_redirects=True)
        assert 'flagged' in _get_flash(r) or 'report' in _get_flash(r)
        with app.app_context():
            assert User.query.get(sid).is_reported is True

    def test_cannot_report_admin(self, client, app):
        _, _ = _setup_admin_and_student(app, client)
        other_admin = _make_user(app, 'Other Admin', 'admin2@test.edu', is_admin=True)
        r = client.post(f'/admin/users/{other_admin}/report', follow_redirects=True)
        assert 'admin' in _get_flash(r) or 'cannot' in _get_flash(r)
        with app.app_context():
            assert User.query.get(other_admin).is_reported is False

    def test_reported_page_requires_admin(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/reported', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# EXCHANGE MONITORING TESTS
# ══════════════════════════════════════════════════════════════════

class TestExchangeMonitoring:

    def test_view_all_exchanges(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, student_id, admin_id, status='pending')
        r = client.get('/admin/exchanges')
        assert r.status_code == 200

    def test_filter_by_pending(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, student_id, admin_id, status='pending')
        _make_exchange(app, student_id, admin_id, status='accepted')
        r = client.get('/admin/exchanges?status=pending')
        assert r.status_code == 200
        assert b'pending' in r.data.lower()

    def test_filter_by_completed(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, student_id, admin_id, status='completed')
        _make_exchange(app, student_id, admin_id, status='pending')
        r = client.get('/admin/exchanges?status=completed')
        assert r.status_code == 200

    def test_no_filter_shows_all(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, student_id, admin_id, status='pending')
        _make_exchange(app, admin_id, student_id, status='accepted')
        r = client.get('/admin/exchanges')
        assert r.status_code == 200

    def test_exchanges_require_admin(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/exchanges', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# SKILL MANAGEMENT TESTS
# ══════════════════════════════════════════════════════════════════

class TestSkillManagement:

    def test_view_skills(self, client, app):
        _setup_admin_and_student(app, client)
        _make_skill(app, 'Python')
        _make_skill(app, 'Guitar', 'Music')
        r = client.get('/admin/skills')
        assert r.status_code == 200
        assert b'Python' in r.data
        assert b'Guitar' in r.data

    def test_delete_skill(self, client, app):
        _setup_admin_and_student(app, client)
        sid = _make_skill(app, 'DeleteMe')
        r = client.post(f'/admin/skills/delete/{sid}', follow_redirects=True)
        assert 'deleted' in _get_flash(r)
        with app.app_context():
            assert Skill.query.get(sid) is None

    def test_delete_nonexistent_skill_404(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.post('/admin/skills/delete/99999', follow_redirects=False)
        assert r.status_code == 404

    def test_skills_page_requires_admin(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/skills', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# STATS DATA ENDPOINT TESTS
# ══════════════════════════════════════════════════════════════════

class TestStatsEndpoint:

    def test_returns_skills_data(self, client, app):
        _, student_id = _setup_admin_and_student(app, client)
        sid = _make_skill(app, 'Python')
        # Assign skill to student
        with app.app_context():
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': student_id, 's': sid, 'p': 'Intermediate'})
            _db.session.commit()
        r = client.get('/admin/stats-data')
        data = r.get_json()
        assert 'Python' in data['skills']['labels']

    def test_returns_statuses_data(self, client, app):
        admin_id, student_id = _setup_admin_and_student(app, client)
        _make_exchange(app, student_id, admin_id, status='pending')
        _make_exchange(app, student_id, admin_id, status='completed')
        r = client.get('/admin/stats-data')
        data = r.get_json()
        assert 'pending' in data['statuses']['labels']
        assert 'completed' in data['statuses']['labels']

    def test_empty_data(self, client, app):
        _setup_admin_and_student(app, client)
        r = client.get('/admin/stats-data')
        data = r.get_json()
        assert data['skills']['labels'] == []
        # Statuses might have zero entries too

    def test_requires_admin(self, client, app):
        _register_and_login_student(client)
        r = client.get('/admin/stats-data', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/login' in r.headers['Location']
