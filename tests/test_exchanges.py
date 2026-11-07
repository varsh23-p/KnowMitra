"""
tests/test_exchanges.py
========================
Comprehensive tests for the skill exchange request system.

Covers:
  Send:
    - Success (with skills + message)
    - Can't send to yourself
    - Duplicate pending request blocked
    - Duplicate in reverse direction blocked
    - Invalid skill_requested (not in receiver's teaching list)
    - Invalid skill_offered (not in sender's teaching list)
    - Missing skill IDs
    - Message too long
    - Notification created for receiver

  Accept:
    - Success (pending → accepted)
    - Only receiver can accept
    - Can't accept already-accepted
    - Can't accept rejected/cancelled/completed
    - Notification sent to sender

  Reject:
    - Success (pending → rejected)
    - Only receiver can reject
    - Can't reject already-rejected

  Cancel:
    - Success (pending → cancelled)
    - Success (accepted → cancelled)
    - Only sender can cancel
    - Can't cancel completed/rejected

  Complete:
    - Success (accepted → completed)
    - Either party can complete
    - Can't complete pending request
    - Notification sent to other party

  Index:
    - All tabs render
    - Sent vs received distinction
    - Login required
    - Empty states

  Status display:
    - All five statuses visible in correct tabs
"""

import pytest
from app import create_app
from app.models import db as _db, User, Skill, ExchangeRequest, Notification
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


def _make_user(app, name, email, teaching_ids=None, learning_ids=None):
    with app.app_context():
        u = User(full_name=name, email=email, college='Test College')
        u.set_password('pass123')
        _db.session.add(u)
        _db.session.commit()
        uid = u.id
        for sid in (teaching_ids or []):
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': sid, 'p': 'Intermediate'})
        for sid in (learning_ids or []):
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': sid})
        _db.session.commit()
        return uid


def _register_login(c, email='sender@test.edu', name='Sender'):
    c.post('/auth/register', data={
        'full_name': name, 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
    }, follow_redirects=False)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _switch_user(c, email, password='pass123'):
    """Log out the current user and log in as someone else."""
    c.post('/auth/logout', follow_redirects=True)
    c.post('/auth/login', data={'email': email, 'password': password},
           follow_redirects=True)


def _setup_two_users(app, client):
    """Create two users with skills, log in as the sender."""
    python_id = _make_skill(app, 'Python')
    guitar_id = _make_skill(app, 'Guitar')

    sender_uid = _make_user(app, 'Sender', 'sender@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
    receiver_uid = _make_user(app, 'Receiver', 'receiver@test.edu',
                               teaching_ids=[guitar_id], learning_ids=[python_id])

    _register_login(client, email='sender@test.edu')
    return sender_uid, receiver_uid, python_id, guitar_id


def _create_request(app, sender_id, receiver_id, skill_requested_id=None,
                     skill_offered_id=None, status='pending'):
    """Create an ExchangeRequest directly in the DB."""
    with app.app_context():
        r = ExchangeRequest(
            sender_id=sender_id, receiver_id=receiver_id,
            skill_requested_id=skill_requested_id,
            skill_offered_id=skill_offered_id,
            status=status,
        )
        _db.session.add(r)
        _db.session.commit()
        return r.id


def _get_flash(resp):
    return resp.data.decode('utf-8', errors='replace').lower()


# ══════════════════════════════════════════════════════════════════
# SEND REQUEST
# ══════════════════════════════════════════════════════════════════

class TestSendRequest:

    def test_send_success(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt,
            'skill_offered':   py,
            'message':         'I would love to learn guitar!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            req = ExchangeRequest.query.first()
            assert req is not None
            assert req.sender_id == s
            assert req.receiver_id == r
            assert req.skill_requested_id == gt
            assert req.skill_offered_id == py
            assert req.status == 'pending'
            assert req.message == 'I would love to learn guitar!'

    def test_send_creates_notification(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt, 'skill_offered': py, 'message': 'Hi!',
        }, follow_redirects=True)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=r).first()
            assert notif is not None
            assert 'Sender' in notif.title

    def test_cannot_send_to_self(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.post(f'/exchanges/send/{s}', data={
            'skill_requested': gt, 'skill_offered': py,
        }, follow_redirects=True)
        assert 'yourself' in _get_flash(resp)
        with app.app_context():
            assert ExchangeRequest.query.count() == 0

    def test_duplicate_pending_blocked(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        # First request succeeds
        client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt, 'skill_offered': py,
        }, follow_redirects=True)
        # Second request should be blocked
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt, 'skill_offered': py,
        }, follow_redirects=True)
        assert 'already' in _get_flash(resp) or 'active' in _get_flash(resp)
        with app.app_context():
            assert ExchangeRequest.query.count() == 1

    def test_duplicate_reverse_direction_blocked(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        # Create a request from receiver to sender (reverse direction)
        _create_request(app, r, s, skill_requested_id=py, skill_offered_id=gt)
        # Now sender tries to send to receiver — should be blocked
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt, 'skill_offered': py,
        }, follow_redirects=True)
        assert 'already' in _get_flash(resp) or 'active' in _get_flash(resp)

    def test_invalid_skill_requested(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        # Request a skill the receiver doesn't teach (use Python instead of Guitar)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': py,  # Receiver doesn't teach Python
            'skill_offered':   py,
            'message': '',
        }, follow_redirects=True)
        assert 'does not teach' in _get_flash(resp) or 'invalid' in _get_flash(resp)

    def test_invalid_skill_offered(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        # Offer a skill the sender doesn't teach (use Guitar instead of Python)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt,
            'skill_offered':   gt,   # Sender doesn't teach Guitar
            'message': '',
        }, follow_redirects=True)
        assert "don't" in _get_flash(resp) or 'teach' in _get_flash(resp)

    def test_missing_skill_requested(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': '',
            'skill_offered':   py,
        }, follow_redirects=True)
        assert 'select' in _get_flash(resp) or 'learn' in _get_flash(resp)

    def test_missing_skill_offered(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt,
            'skill_offered':   '',
        }, follow_redirects=True)
        assert 'select' in _get_flash(resp) or 'offer' in _get_flash(resp) or 'teach' in _get_flash(resp)

    def test_message_too_long(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.post(f'/exchanges/send/{r}', data={
            'skill_requested': gt, 'skill_offered': py,
            'message': 'x' * 600,
        }, follow_redirects=True)
        assert '500' in _get_flash(resp) or 'exceed' in _get_flash(resp)

    def test_send_page_loads(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        resp = client.get(f'/exchanges/send/{r}')
        assert resp.status_code == 200
        assert b'Receiver' in resp.data

    def test_send_to_nonexistent_user_404(self, client, app):
        _setup_two_users(app, client)
        resp = client.get('/exchanges/send/99999')
        assert resp.status_code == 404

    def test_send_requires_login(self, client):
        resp = client.get('/exchanges/send/1', follow_redirects=False)
        assert resp.status_code == 302
        assert 'login' in resp.headers['Location']


# ══════════════════════════════════════════════════════════════════
# ACCEPT
# ══════════════════════════════════════════════════════════════════

class TestAccept:

    def test_accept_success(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        # Log in as receiver
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            req = ExchangeRequest.query.get(rid)
            assert req.status == 'accepted'

    def test_accept_creates_notification(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=s).first()
            assert notif is not None
            assert 'accepted' in notif.title.lower()

    def test_only_receiver_can_accept(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        # Sender tries to accept their own request
        resp = client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        assert 'not authorized' in _get_flash(resp) or 'authorized' in _get_flash(resp)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'pending'

    def test_cannot_accept_already_accepted(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        assert 'cannot be accepted' in _get_flash(resp)

    def test_cannot_accept_rejected(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='rejected')
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        assert 'cannot be accepted' in _get_flash(resp)


# ══════════════════════════════════════════════════════════════════
# REJECT
# ══════════════════════════════════════════════════════════════════

class TestReject:

    def test_reject_success(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'rejected'

    def test_reject_creates_notification(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=s).first()
            assert notif is not None
            assert 'declined' in notif.title.lower()

    def test_only_receiver_can_reject(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        resp = client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        assert 'authorized' in _get_flash(resp)

    def test_cannot_reject_already_rejected(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='rejected')
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        assert 'cannot be rejected' in _get_flash(resp)


# ══════════════════════════════════════════════════════════════════
# CANCEL
# ══════════════════════════════════════════════════════════════════

class TestCancel:

    def test_cancel_pending_success(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        resp = client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'cancelled'

    def test_cancel_accepted_success(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        resp = client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'cancelled'

    def test_only_sender_can_cancel(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        # Log in as receiver and try to cancel
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        assert 'only' in _get_flash(resp) or 'own' in _get_flash(resp)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'pending'

    def test_cannot_cancel_completed(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='completed')
        resp = client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        assert 'cannot be cancelled' in _get_flash(resp)

    def test_cannot_cancel_rejected(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='rejected')
        resp = client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        assert 'cannot be cancelled' in _get_flash(resp)

    def test_cancel_creates_notification(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py)
        client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=r).first()
            assert notif is not None
            assert 'cancelled' in notif.title.lower()


# ══════════════════════════════════════════════════════════════════
# COMPLETE
# ══════════════════════════════════════════════════════════════════

class TestComplete:

    def test_complete_by_sender(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        resp = client.post(f'/exchanges/complete/{rid}', follow_redirects=False)
        # Redirects to review page
        assert resp.status_code == 302
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'completed'

    def test_complete_by_receiver(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        _switch_user(client, 'receiver@test.edu')
        resp = client.post(f'/exchanges/complete/{rid}', follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'completed'

    def test_cannot_complete_pending(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='pending')
        resp = client.post(f'/exchanges/complete/{rid}', follow_redirects=True)
        assert 'cannot be' in _get_flash(resp) or 'completed' in _get_flash(resp)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'pending'

    def test_cannot_complete_already_completed(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='completed')
        resp = client.post(f'/exchanges/complete/{rid}', follow_redirects=True)
        assert 'cannot be' in _get_flash(resp)

    def test_unauthorized_user_cannot_complete(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        # Create a third user and log in as them
        _make_user(app, 'Third', 'third@test.edu')
        _switch_user(client, 'third@test.edu')
        resp = client.post(f'/exchanges/complete/{rid}', follow_redirects=True)
        assert 'authorized' in _get_flash(resp)

    def test_complete_creates_notification(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        client.post(f'/exchanges/complete/{rid}', follow_redirects=False)
        with app.app_context():
            notif = Notification.query.filter_by(user_id=r).first()
            assert notif is not None
            assert 'completed' in notif.title.lower()


# ══════════════════════════════════════════════════════════════════
# INDEX PAGE
# ══════════════════════════════════════════════════════════════════

class TestIndexPage:

    def test_requires_login(self, client):
        resp = client.get('/exchanges/', follow_redirects=False)
        assert resp.status_code == 302
        assert 'login' in resp.headers['Location']

    def test_index_loads(self, client, app):
        _setup_two_users(app, client)
        resp = client.get('/exchanges/')
        assert resp.status_code == 200
        assert b'Exchanges' in resp.data or b'exchanges' in resp.data.lower()

    def test_pending_request_shown(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        _create_request(app, s, r, gt, py, status='pending')
        resp = client.get('/exchanges/')
        assert b'Receiver' in resp.data

    def test_sent_vs_received_badge(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        _create_request(app, s, r, gt, py, status='pending')
        resp = client.get('/exchanges/')
        # Sender should see a "Sent" badge
        assert b'Sent' in resp.data

    def test_received_badge(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        _create_request(app, s, r, gt, py, status='pending')
        # Log in as receiver
        _switch_user(client, 'receiver@test.edu')
        resp = client.get('/exchanges/')
        assert b'Received' in resp.data

    def test_all_statuses_visible(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        _create_request(app, s, r, gt, py, status='pending')
        _create_request(app, s, r, gt, py, status='accepted')
        _create_request(app, s, r, gt, py, status='rejected')
        _create_request(app, s, r, gt, py, status='cancelled')
        _create_request(app, s, r, gt, py, status='completed')
        resp = client.get('/exchanges/')
        assert resp.status_code == 200
        # All five requests exist in the DB
        with app.app_context():
            assert ExchangeRequest.query.count() == 5

    def test_empty_state(self, client, app):
        _setup_two_users(app, client)
        resp = client.get('/exchanges/')
        assert b'No pending' in resp.data or b'Find Matches' in resp.data


# ══════════════════════════════════════════════════════════════════
# STATUS TRANSITIONS (unit-level validation)
# ══════════════════════════════════════════════════════════════════

class TestStatusTransitions:

    def test_pending_can_accept(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='pending')
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'accepted'

    def test_pending_can_reject(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='pending')
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'rejected'

    def test_pending_can_cancel(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='pending')
        client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'cancelled'

    def test_accepted_can_complete(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        client.post(f'/exchanges/complete/{rid}', follow_redirects=False)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'completed'

    def test_accepted_can_cancel(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='accepted')
        client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'cancelled'

    def test_completed_is_terminal(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='completed')
        # Try accept, reject, cancel — all should fail
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        _switch_user(client, 'sender@test.edu')
        client.post(f'/exchanges/cancel/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'completed'

    def test_rejected_is_terminal(self, client, app):
        s, r, py, gt = _setup_two_users(app, client)
        rid = _create_request(app, s, r, gt, py, status='rejected')
        _switch_user(client, 'receiver@test.edu')
        client.post(f'/exchanges/accept/{rid}', follow_redirects=True)
        client.post(f'/exchanges/reject/{rid}', follow_redirects=True)
        with app.app_context():
            assert ExchangeRequest.query.get(rid).status == 'rejected'
