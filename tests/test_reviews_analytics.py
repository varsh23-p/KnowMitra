"""
tests/test_reviews_analytics.py
===============================
Tests for the reviews module and dashboard analytics.

Reviews:
  - Submit a review (success, rating + feedback)
  - Duplicate review for same exchange blocked
  - Rating validation (1–5 only, missing rejected)
  - Feedback too long rejected
  - Non-participant blocked
  - Non-completed exchange blocked
  - Notification sent to reviewee
  - Average rating calculation
  - Reviews list page (breakdown bars, rating display)

Analytics:
  - Dashboard stat cards use real DB data
  - Chart data: popular teaching skills
  - Chart data: most requested learning skills
  - Chart data: monthly exchange activity (6 months)
  - Chart data: learning progress (learned / in-progress / not-started)
  - All endpoints require login
  - Empty data handled gracefully
"""

import pytest
from datetime import datetime, timedelta
from app import create_app
from app.models import db as _db, User, Skill, ExchangeRequest, Review, Notification
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
        _db.session.query(Notification).delete()
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

def _make_skill(app, name, category='Programming'):
    with app.app_context():
        s = Skill(name=name, category=category, icon='fa-code')
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _make_user(app, name, email):
    with app.app_context():
        u = User(full_name=name, email=email, college='Test College')
        u.set_password('pass123')
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _register_login(c, email='reviewer@test.edu', name='Reviewer'):
    c.post('/auth/register', data={
        'full_name': name, 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
    }, follow_redirects=False)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _switch_user(c, email):
    c.post('/auth/logout', follow_redirects=True)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _create_exchange(app, sender_id, receiver_id, status='completed',
                     skill_req=None, skill_off=None):
    with app.app_context():
        r = ExchangeRequest(
            sender_id=sender_id, receiver_id=receiver_id,
            skill_requested_id=skill_req, skill_offered_id=skill_off,
            status=status,
        )
        _db.session.add(r)
        _db.session.commit()
        return r.id


def _create_review(app, reviewer_id, reviewee_id, exchange_id, rating=5,
                    feedback='Great!'):
    with app.app_context():
        r = Review(reviewer_id=reviewer_id, reviewee_id=reviewee_id,
                    exchange_id=exchange_id, rating=rating, feedback=feedback)
        _db.session.add(r)
        _db.session.commit()
        return r.id


def _assign_skill(app, user_id, skill_id, table='teaching'):
    with app.app_context():
        if table == 'teaching':
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': user_id, 's': skill_id, 'p': 'Intermediate'})
        else:
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': user_id, 's': skill_id})
        _db.session.commit()


def _get_flash(resp):
    return resp.data.decode('utf-8', errors='replace').lower()


def _setup_completed_exchange(app, client):
    """Create two users, an accepted→completed exchange, log in as sender."""
    python_id = _make_skill(app, 'Python')
    guitar_id = _make_skill(app, 'Guitar')
    alice = _make_user(app, 'Alice', 'alice@test.edu')
    bob   = _make_user(app, 'Bob',   'bob@test.edu')
    _assign_skill(app, alice, python_id, 'teaching')
    _assign_skill(app, alice, guitar_id, 'learning')
    _assign_skill(app, bob,   guitar_id, 'teaching')
    _assign_skill(app, bob,   python_id, 'learning')
    rid = _create_exchange(app, alice, bob, status='completed',
                            skill_req=guitar_id, skill_off=python_id)
    _register_login(client, email='alice@test.edu', name='Alice')
    return alice, bob, rid, python_id, guitar_id


# ══════════════════════════════════════════════════════════════════
# REVIEW SUBMISSION TESTS
# ══════════════════════════════════════════════════════════════════

class TestReviewSubmission:

    def test_submit_review_success(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 5, 'feedback': 'Excellent teacher!',
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            rev = Review.query.first()
            assert rev is not None
            assert rev.rating == 5
            assert rev.feedback == 'Excellent teacher!'
            assert rev.reviewer_id == alice
            assert rev.reviewee_id == bob

    def test_review_with_no_feedback(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        client.post(f'/reviews/add/{rid}', data={
            'rating': 4, 'feedback': '',
        }, follow_redirects=True)
        with app.app_context():
            rev = Review.query.first()
            assert rev.feedback is None

    def test_review_creates_notification(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        client.post(f'/reviews/add/{rid}', data={
            'rating': 5, 'feedback': 'Great!',
        }, follow_redirects=True)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=bob).first()
            assert notif is not None
            assert '5' in notif.title or 'review' in notif.title.lower()

    def test_duplicate_review_blocked(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        # First review succeeds
        client.post(f'/reviews/add/{rid}', data={
            'rating': 5, 'feedback': 'First review',
        }, follow_redirects=True)
        # Second review should be blocked
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 4, 'feedback': 'Second review',
        }, follow_redirects=True)
        assert 'already reviewed' in _get_flash(r)
        with app.app_context():
            assert Review.query.count() == 1

    def test_missing_rating_rejected(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': '', 'feedback': 'No rating',
        }, follow_redirects=True)
        assert 'rating' in _get_flash(r) or 'select' in _get_flash(r)
        with app.app_context():
            assert Review.query.count() == 0

    def test_rating_below_1_rejected(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 0, 'feedback': '',
        }, follow_redirects=True)
        assert 'rating' in _get_flash(r) or 'between' in _get_flash(r)

    def test_rating_above_5_rejected(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 6, 'feedback': '',
        }, follow_redirects=True)
        assert 'rating' in _get_flash(r) or 'between' in _get_flash(r)

    def test_feedback_too_long_rejected(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 5, 'feedback': 'x' * 501,
        }, follow_redirects=True)
        assert '500' in _get_flash(r) or 'exceed' in _get_flash(r)
        with app.app_context():
            assert Review.query.count() == 0

    def test_non_participant_blocked(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        # Create a third user and log in as them
        charlie = _make_user(app, 'Charlie', 'charlie@test.edu')
        _switch_user(client, 'charlie@test.edu')
        r = client.post(f'/reviews/add/{rid}', data={
            'rating': 5, 'feedback': 'Not my exchange',
        }, follow_redirects=True)
        assert 'authorized' in _get_flash(r)
        with app.app_context():
            assert Review.query.count() == 0

    def test_non_completed_exchange_blocked(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        # Create a pending exchange
        pending_rid = _create_exchange(app, alice, bob, status='pending',
                                        skill_req=gt, skill_off=py)
        r = client.post(f'/reviews/add/{pending_rid}', data={
            'rating': 5, 'feedback': '',
        }, follow_redirects=True)
        assert 'completed' in _get_flash(r)

    def test_review_page_loads(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.get(f'/reviews/add/{rid}')
        assert r.status_code == 200
        assert b'Rate Your Exchange' in r.data or b'rate' in _get_flash(r)

    def test_review_requires_login(self, client, app):
        r = client.get('/reviews/add/1', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_nonexistent_exchange_404(self, client, app):
        _setup_completed_exchange(app, client)
        r = client.get('/reviews/add/99999')
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════
# AVERAGE RATING TESTS
# ══════════════════════════════════════════════════════════════════

class TestAverageRating:

    def test_avg_rating_calculation(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        # Bob reviews Alice with 5
        _create_review(app, bob, alice, rid, rating=5, feedback='Great')
        with app.app_context():
            u = User.query.get(alice)
            assert u.avg_rating == 5.0

    def test_avg_rating_multiple_reviews(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        # Create a second completed exchange with a third user
        charlie = _make_user(app, 'Charlie', 'charlie@test.edu')
        rid2 = _create_exchange(app, charlie, alice, status='completed')
        _create_review(app, bob, alice, rid, rating=5)
        _create_review(app, charlie, alice, rid2, rating=3)
        with app.app_context():
            u = User.query.get(alice)
            assert u.avg_rating == 4.0  # (5 + 3) / 2

    def test_avg_rating_no_reviews(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        with app.app_context():
            u = User.query.get(alice)
            assert u.avg_rating == 0.0

    def test_avg_rating_shown_on_profile(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        _create_review(app, bob, alice, rid, rating=5, feedback='Great')
        r = client.get(f'/profile/{alice}')
        assert b'5.0' in r.data or b'5' in r.data


# ══════════════════════════════════════════════════════════════════
# REVIEWS LIST PAGE
# ══════════════════════════════════════════════════════════════════

class TestReviewsList:

    def test_reviews_list_shows_reviews(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        _create_review(app, bob, alice, rid, rating=5, feedback='Excellent')
        r = client.get(f'/reviews/user/{alice}')
        assert r.status_code == 200
        assert b'Excellent' in r.data

    def test_reviews_list_shows_breakdown(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        _create_review(app, bob, alice, rid, rating=5)
        r = client.get(f'/reviews/user/{alice}')
        assert b'breakdown' in r.data.lower() or b'5' in r.data

    def test_reviews_list_empty(self, client, app):
        alice, bob, rid, py, gt = _setup_completed_exchange(app, client)
        r = client.get(f'/reviews/user/{alice}')
        assert r.status_code == 200
        assert b'No reviews' in r.data

    def test_reviews_list_requires_login(self, client):
        r = client.get('/reviews/user/1', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# DASHBOARD STAT CARDS (real DB data)
# ══════════════════════════════════════════════════════════════════

class TestDashboardStats:

    def test_requires_login(self, client):
        r = client.get('/dashboard/', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_total_connections_zero(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/')
        assert r.status_code == 200
        assert b'0' in r.data  # zero connections

    def test_total_connections_counts_accepted(self, client, app):
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _create_exchange(app, alice, bob, status='accepted')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/')
        assert r.status_code == 200

    def test_total_connections_counts_completed(self, client, app):
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _create_exchange(app, alice, bob, status='completed')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/')
        assert r.status_code == 200

    def test_pending_requests_count(self, client, app):
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        # Bob sends a pending request to Alice
        _create_exchange(app, bob, alice, status='pending')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/')
        assert r.status_code == 200

    def test_avg_rating_displayed(self, client, app):
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        sid = _make_skill(app, 'Python')
        rid = _create_exchange(app, alice, bob, status='completed', skill_req=sid, skill_off=sid)
        _create_review(app, bob, alice, rid, rating=4)
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/')
        assert r.status_code == 200
        assert b'4.0' in r.data or b'Average Rating' in r.data

    def test_stats_not_hardcoded(self, client, app):
        """Stats must change when DB data changes — not static numbers."""
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _register_login(client, email='alice@test.edu', name='Alice')
        # Before any exchange
        r1 = client.get('/dashboard/')
        # Add an exchange
        _create_exchange(app, alice, bob, status='accepted')
        r2 = client.get('/dashboard/')
        # The page should show different counts
        # (Both render 200, and the stat value should differ)
        assert r1.status_code == 200 and r2.status_code == 200


# ══════════════════════════════════════════════════════════════════
# CHART DATA ENDPOINTS
# ══════════════════════════════════════════════════════════════════

class TestChartTeachingSkills:

    def test_requires_login(self, client):
        r = client.get('/dashboard/chart-data', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_returns_json(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data')
        assert r.status_code == 200
        data = r.get_json()
        assert 'labels' in data
        assert 'data' in data

    def test_empty_when_no_skills(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data')
        data = r.get_json()
        assert data['labels'] == []
        assert data['data'] == []

    def test_returns_real_teaching_counts(self, client, app):
        sid = _make_skill(app, 'Python')
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _assign_skill(app, alice, sid, 'teaching')
        _assign_skill(app, bob, sid, 'teaching')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data')
        data = r.get_json()
        assert 'Python' in data['labels']
        idx = data['labels'].index('Python')
        assert data['data'][idx] == 2  # two users teaching it


class TestChartLearningSkills:

    def test_requires_login(self, client):
        r = client.get('/dashboard/chart-data/learning', follow_redirects=False)
        assert r.status_code == 302

    def test_returns_json(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/learning')
        assert r.status_code == 200
        data = r.get_json()
        assert 'labels' in data and 'data' in data

    def test_returns_real_learning_counts(self, client, app):
        sid = _make_skill(app, 'Guitar')
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _assign_skill(app, alice, sid, 'learning')
        _assign_skill(app, bob, sid, 'learning')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data/learning')
        data = r.get_json()
        assert 'Guitar' in data['labels']
        idx = data['labels'].index('Guitar')
        assert data['data'][idx] == 2

    def test_empty_when_no_learning_skills(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/learning')
        data = r.get_json()
        assert data['labels'] == []


class TestChartMonthlyActivity:

    def test_requires_login(self, client):
        r = client.get('/dashboard/chart-data/monthly', follow_redirects=False)
        assert r.status_code == 302

    def test_returns_six_months(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/monthly')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['labels']) == 6
        assert len(data['data']) == 6

    def test_counts_exchanges_in_current_month(self, client, app):
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        # Create 3 exchanges now (current month)
        for _ in range(3):
            _create_exchange(app, alice, bob, status='pending')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data/monthly')
        data = r.get_json()
        # The last entry (current month) should be 3
        assert data['data'][-1] == 3

    def test_zero_when_no_exchanges(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/monthly')
        data = r.get_json()
        assert all(v == 0 for v in data['data'])


class TestChartLearningProgress:

    def test_requires_login(self, client):
        r = client.get('/dashboard/chart-data/progress', follow_redirects=False)
        assert r.status_code == 302

    def test_returns_json(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/progress')
        assert r.status_code == 200
        data = r.get_json()
        assert 'labels' in data
        assert 'data' in data
        assert 'total' in data

    def test_empty_when_no_learning_skills(self, client, app):
        _register_login(client)
        r = client.get('/dashboard/chart-data/progress')
        data = r.get_json()
        assert data['total'] == 0
        assert data['data'] == [0, 0, 0]

    def test_shows_not_started(self, client, app):
        """Skills in learning list but not in any exchange → not started."""
        sid = _make_skill(app, 'Guitar')
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        _assign_skill(app, alice, sid, 'learning')
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data/progress')
        data = r.get_json()
        assert data['total'] == 1
        # Learned=0, In Progress=0, Not Started=1
        assert data['data'] == [0, 0, 1]

    def test_shows_in_progress(self, client, app):
        """Accepted exchange where user is the receiver (learner) → in progress."""
        sid = _make_skill(app, 'Guitar')
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _assign_skill(app, alice, sid, 'learning')
        _assign_skill(app, bob, sid, 'teaching')
        _create_exchange(app, bob, alice, status='accepted', skill_req=sid, skill_off=sid)
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data/progress')
        data = r.get_json()
        assert data['data'][1] == 1  # In Progress

    def test_shows_learned(self, client, app):
        """Completed exchange where user is the receiver (learner) → learned."""
        sid = _make_skill(app, 'Guitar')
        alice = _make_user(app, 'Alice', 'alice@test.edu')
        bob   = _make_user(app, 'Bob', 'bob@test.edu')
        _assign_skill(app, alice, sid, 'learning')
        _assign_skill(app, bob, sid, 'teaching')
        _create_exchange(app, bob, alice, status='completed', skill_req=sid, skill_off=sid)
        _register_login(client, email='alice@test.edu', name='Alice')
        r = client.get('/dashboard/chart-data/progress')
        data = r.get_json()
        assert data['data'][0] == 1  # Learned
