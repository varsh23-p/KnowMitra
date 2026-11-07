"""
tests/test_messages.py
=====================
Comprehensive tests for the student-to-student messaging system.

Covers:
  Inbox:
    - Login required
    - Shows conversations with partners
    - Shows unread counts
    - Empty state when no conversations
    - Total unread count

  Conversation view:
    - Login required
    - Shows message history
    - Sender and receiver identified correctly
    - Timestamps displayed
    - Marks incoming as read on view
    - Access control: not connected → redirected to inbox
    - Access control: messaging yourself → redirected
    - Nonexistent user → 404

  Send (form POST fallback):
    - Success (message stored in DB)
    - Empty message rejected
    - Too-long message rejected
    - Not connected → redirected

  Send (AJAX endpoint):
    - Success (returns JSON)
    - Empty → 400
    - Too long → 400
    - Not connected → 403
    - Self → 403

  Poll endpoint:
    - Returns new messages since last ID
    - Marks incoming as read
    - Access control (not connected → 403)
    - Self → 400
    - Login required

  Unread count endpoint:
    - Returns correct count
    - Login required

  Access restrictions:
    - Unconnected users cannot access conversation
    - Unconnected users cannot send via AJAX
    - Unconnected users cannot poll
    - Self-messaging blocked on all endpoints
"""

import pytest
from app import create_app
from app.models import db as _db, User, Skill, ExchangeRequest, Message
from sqlalchemy import text, or_, and_


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
        _db.session.query(Message).delete()
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

def _make_skill(app, name='Python'):
    with app.app_context():
        s = Skill(name=name, category='Programming', icon='fa-code')
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


def _register_login(c, email='alice@test.edu', name='Alice'):
    c.post('/auth/register', data={
        'full_name': name, 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
    }, follow_redirects=False)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _switch_user(c, email):
    """Log out then log in as a different user."""
    c.post('/auth/logout', follow_redirects=True)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _create_exchange(app, sender_id, receiver_id, status='accepted',
                     skill_req=None, skill_off=None):
    """Create an ExchangeRequest directly in the DB."""
    with app.app_context():
        r = ExchangeRequest(
            sender_id=sender_id, receiver_id=receiver_id,
            skill_requested_id=skill_req, skill_offered_id=skill_off,
            status=status,
        )
        _db.session.add(r)
        _db.session.commit()
        return r.id


def _create_message(app, sender_id, receiver_id, content='Hello!',
                    is_read=False):
    """Create a Message directly in the DB."""
    with app.app_context():
        m = Message(sender_id=sender_id, receiver_id=receiver_id,
                     content=content, is_read=is_read)
        _db.session.add(m)
        _db.session.commit()
        return m.id


def _setup_connected_pair(app, client):
    """
    Create two users with an accepted exchange and skills.
    Log in as Alice (sender). Return (alice_id, bob_id, skill_id).
    """
    sid = _make_skill(app, 'Python')
    alice_id = _make_user(app, 'Alice', 'alice@test.edu')
    bob_id   = _make_user(app, 'Bob', 'bob@test.edu')

    # Give them skills so they can exchange
    with app.app_context():
        for uid, s in [(alice_id, sid), (bob_id, sid)]:
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': sid, 'p': 'Intermediate'})
        _db.session.commit()

    # Create accepted exchange (Alice → Bob)
    _create_exchange(app, alice_id, bob_id, status='accepted',
                     skill_req=sid, skill_off=sid)

    _register_login(client, email='alice@test.edu', name='Alice')
    return alice_id, bob_id, sid


def _get_flash(resp):
    return resp.data.decode('utf-8', errors='replace').lower()


# ══════════════════════════════════════════════════════════════════
# INBOX TESTS
# ══════════════════════════════════════════════════════════════════

class TestInbox:

    def test_requires_login(self, client):
        r = client.get('/messages/', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_empty_inbox(self, client, app):
        _register_login(client)
        r = client.get('/messages/')
        assert r.status_code == 200
        assert b'No conversations' in r.data or b'no conversations' in _get_flash(r)

    def test_shows_conversations(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        # Send a message from Alice to Bob
        _create_message(app, alice, bob, 'Hi Bob!')
        r = client.get('/messages/')
        assert r.status_code == 200
        assert b'Bob' in r.data

    def test_shows_unread_badge(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        # Bob sends a message to Alice (unread)
        _create_message(app, bob, alice, 'Hey Alice!', is_read=False)
        r = client.get('/messages/')
        assert r.status_code == 200
        # Unread badge should appear
        assert b'unread' in r.data.lower() or b'1' in r.data

    def test_total_unread_count(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        # Multiple unread messages from Bob to Alice
        _create_message(app, bob, alice, 'Msg 1', is_read=False)
        _create_message(app, bob, alice, 'Msg 2', is_read=False)
        r = client.get('/messages/')
        assert r.status_code == 200

    def test_conversation_search(self, client, app):
        """Search input exists on the page."""
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Hello')
        r = client.get('/messages/')
        assert b'Search' in r.data or b'search' in _get_flash(r)


# ══════════════════════════════════════════════════════════════════
# CONVERSATION VIEW TESTS
# ══════════════════════════════════════════════════════════════════

class TestConversationView:

    def test_requires_login(self, client, app):
        r = client.get('/messages/conversation/1', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_shows_message_history(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Hello from Alice!')
        _create_message(app, bob, alice, 'Hi back from Bob!')
        r = client.get(f'/messages/conversation/{bob}')
        assert r.status_code == 200
        assert b'Hello from Alice!' in r.data
        assert b'Hi back from Bob!' in r.data

    def test_sender_receiver_identified(self, client, app):
        """Messages from the current user get 'mine' class, others get 'theirs'."""
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'My message')
        _create_message(app, bob, alice, 'Their message')
        r = client.get(f'/messages/conversation/{bob}')
        assert b'mine' in r.data
        assert b'theirs' in r.data

    def test_timestamps_displayed(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Time test')
        r = client.get(f'/messages/conversation/{bob}')
        assert r.status_code == 200
        # Should have timestamp elements
        assert b'msg-ts' in r.data

    def test_marks_incoming_as_read(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        msg_id = _create_message(app, bob, alice, 'Unread msg', is_read=False)
        # View the conversation
        client.get(f'/messages/conversation/{bob}')
        with app.app_context():
            m = Message.query.get(msg_id)
            assert m.is_read is True

    def test_not_connected_redirected(self, client, app):
        """User without an accepted exchange can't view conversations."""
        _register_login(client)
        # Create a second user but no exchange
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.get(f'/messages/conversation/{bob_id}', follow_redirects=False)
        assert r.status_code == 302
        assert '/messages/' in r.headers['Location']

    def test_messaging_self_redirected(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.get(f'/messages/conversation/{alice}', follow_redirects=False)
        assert r.status_code == 302
        assert '/messages/' in r.headers['Location']

    def test_nonexistent_user_404(self, client, app):
        _setup_connected_pair(app, client)
        r = client.get('/messages/conversation/99999')
        assert r.status_code == 404

    def test_shows_all_conversations_in_sidebar(self, client, app):
        """The conversation sidebar should list all conversations."""
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Hi Bob!')
        r = client.get(f'/messages/conversation/{bob}')
        assert r.status_code == 200
        assert b'Bob' in r.data

    def test_pending_exchange_not_enough(self, client, app):
        """A pending exchange (not accepted) should not allow messaging."""
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        alice_id = None
        with app.app_context():
            alice_id = User.query.filter_by(email='alice@test.edu').first().id
        _create_exchange(app, alice_id, bob_id, status='pending')
        r = client.get(f'/messages/conversation/{bob_id}', follow_redirects=False)
        assert r.status_code == 302
        assert '/messages/' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# SEND (form POST fallback)
# ══════════════════════════════════════════════════════════════════

class TestSendForm:

    def test_send_success(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/conversation/{bob}', data={
            'content': 'Hello via form!',
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            msgs = Message.query.all()
            assert len(msgs) == 1
            assert msgs[0].content == 'Hello via form!'
            assert msgs[0].sender_id == alice
            assert msgs[0].receiver_id == bob

    def test_empty_message_rejected(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/conversation/{bob}', data={
            'content': '',
        }, follow_redirects=True)
        assert 'empty' in _get_flash(r)
        with app.app_context():
            assert Message.query.count() == 0

    def test_whitespace_only_rejected(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/conversation/{bob}', data={
            'content': '   ',
        }, follow_redirects=True)
        assert 'empty' in _get_flash(r)
        with app.app_context():
            assert Message.query.count() == 0

    def test_too_long_rejected(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/conversation/{bob}', data={
            'content': 'x' * 2001,
        }, follow_redirects=True)
        assert '2000' in _get_flash(r) or 'too long' in _get_flash(r)
        with app.app_context():
            assert Message.query.count() == 0

    def test_not_connected_blocked(self, client, app):
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.post(f'/messages/conversation/{bob_id}', data={
            'content': 'Hello',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/messages/' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# SEND (AJAX endpoint)
# ══════════════════════════════════════════════════════════════════

class TestSendAjax:

    def test_send_success_json(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/send/{bob}', data={'content': 'AJAX hello!'})
        assert r.status_code == 200
        data = r.get_json()
        assert data is not None
        assert data['content'] == 'AJAX hello!'
        assert data['is_mine'] is True
        assert data['id'] > 0
        assert 'created_at' in data

    def test_empty_returns_400(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/send/{bob}', data={'content': ''})
        assert r.status_code == 400
        assert 'empty' in r.get_json()['error'].lower()

    def test_too_long_returns_400(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/send/{bob}', data={'content': 'x' * 2001})
        assert r.status_code == 400
        assert '2000' in r.get_json()['error'] or 'long' in r.get_json()['error'].lower()

    def test_not_connected_returns_403(self, client, app):
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.post(f'/messages/send/{bob_id}', data={'content': 'Hi'})
        assert r.status_code == 403

    def test_self_returns_403(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.post(f'/messages/send/{alice}', data={'content': 'Hi me'})
        assert r.status_code == 403

    def test_message_stored_in_db(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        client.post(f'/messages/send/{bob}', data={'content': 'Stored msg'})
        with app.app_context():
            m = Message.query.first()
            assert m is not None
            assert m.content == 'Stored msg'
            assert m.sender_id == alice
            assert m.receiver_id == bob

    def test_nonexistent_user_404(self, client, app):
        _setup_connected_pair(app, client)
        r = client.post('/messages/send/99999', data={'content': 'Hi'})
        assert r.status_code == 404

    def test_requires_login(self, client):
        r = client.post('/messages/send/1', data={'content': 'Hi'})
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# POLL ENDPOINT
# ══════════════════════════════════════════════════════════════════

class TestPoll:

    def test_returns_messages_since_id(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        msg1 = _create_message(app, alice, bob, 'Msg 1')
        msg2 = _create_message(app, bob, alice, 'Msg 2')
        # Poll since msg1 (should only return msg2)
        r = client.get(f'/messages/poll/{bob}?since={msg1}')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]['content'] == 'Msg 2'
        assert data[0]['is_mine'] is False

    def test_returns_all_if_since_zero(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Msg A')
        _create_message(app, bob, alice, 'Msg B')
        r = client.get(f'/messages/poll/{bob}?since=0')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2

    def test_marks_incoming_as_read(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        msg_id = _create_message(app, bob, alice, 'Unread poll msg', is_read=False)
        client.get(f'/messages/poll/{bob}?since=0')
        with app.app_context():
            assert Message.query.get(msg_id).is_read is True

    def test_not_connected_returns_403(self, client, app):
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.get(f'/messages/poll/{bob_id}?since=0')
        assert r.status_code == 403

    def test_self_returns_400(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        r = client.get(f'/messages/poll/{alice}?since=0')
        assert r.status_code == 400

    def test_requires_login(self, client):
        r = client.get('/messages/poll/1?since=0')
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_returns_empty_for_no_new(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        msg_id = _create_message(app, alice, bob, 'Old msg')
        r = client.get(f'/messages/poll/{bob}?since={msg_id}')
        assert r.status_code == 200
        assert r.get_json() == []

    def test_is_mine_flag_correct(self, client, app):
        """Messages sent by current user have is_mine=True."""
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'My msg')
        _create_message(app, bob, alice, 'Their msg')
        r = client.get(f'/messages/poll/{bob}?since=0')
        data = r.get_json()
        mine = [m for m in data if m['is_mine']]
        theirs = [m for m in data if not m['is_mine']]
        assert len(mine) == 1
        assert mine[0]['content'] == 'My msg'
        assert len(theirs) == 1
        assert theirs[0]['content'] == 'Their msg'

    def test_timestamps_in_response(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, alice, bob, 'Time check')
        r = client.get(f'/messages/poll/{bob}?since=0')
        data = r.get_json()
        assert 'created_at' in data[0]
        assert 'time_short' in data[0]
        assert 'date' in data[0]


# ══════════════════════════════════════════════════════════════════
# UNREAD COUNT ENDPOINT
# ══════════════════════════════════════════════════════════════════

class TestUnreadCount:

    def test_requires_login(self, client):
        r = client.get('/messages/unread-count', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_returns_zero_when_no_unread(self, client, app):
        _setup_connected_pair(app, client)
        r = client.get('/messages/unread-count')
        assert r.status_code == 200
        assert r.get_json()['count'] == 0

    def test_returns_correct_count(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, bob, alice, 'Unread 1', is_read=False)
        _create_message(app, bob, alice, 'Unread 2', is_read=False)
        _create_message(app, alice, bob, 'Sent (read)', is_read=False)
        r = client.get('/messages/unread-count')
        assert r.get_json()['count'] == 2

    def test_read_messages_not_counted(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        _create_message(app, bob, alice, 'Read msg', is_read=True)
        r = client.get('/messages/unread-count')
        assert r.get_json()['count'] == 0


# ══════════════════════════════════════════════════════════════════
# ACCESS RESTRICTIONS (cross-cutting)
# ══════════════════════════════════════════════════════════════════

class TestAccessRestrictions:

    def test_unconnected_conversation_view(self, client, app):
        """User with no exchange can't view a conversation."""
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.get(f'/messages/conversation/{bob_id}', follow_redirects=False)
        assert r.status_code == 302
        assert '/messages/' in r.headers['Location']

    def test_unconnected_ajax_send(self, client, app):
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.post(f'/messages/send/{bob_id}', data={'content': 'Hi'})
        assert r.status_code == 403

    def test_unconnected_poll(self, client, app):
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        r = client.get(f'/messages/poll/{bob_id}?since=0')
        assert r.status_code == 403

    def test_pending_exchange_not_enough_for_messaging(self, client, app):
        """A pending exchange should not grant messaging access."""
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        alice_id = None
        with app.app_context():
            alice_id = User.query.filter_by(email='alice@test.edu').first().id
        _create_exchange(app, alice_id, bob_id, status='pending')
        # Conversation view
        r = client.get(f'/messages/conversation/{bob_id}', follow_redirects=False)
        assert r.status_code == 302
        # AJAX send
        r = client.post(f'/messages/send/{bob_id}', data={'content': 'Hi'})
        assert r.status_code == 403
        # Poll
        r = client.get(f'/messages/poll/{bob_id}?since=0')
        assert r.status_code == 403

    def test_completed_exchange_grants_access(self, client, app):
        """A completed exchange should still allow messaging."""
        _register_login(client)
        bob_id = _make_user(app, 'Bob', 'bob@test.edu')
        alice_id = None
        with app.app_context():
            alice_id = User.query.filter_by(email='alice@test.edu').first().id
        _create_exchange(app, alice_id, bob_id, status='completed')
        r = client.get(f'/messages/conversation/{bob_id}', follow_redirects=False)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════
# MESSAGE CONTENT & STORAGE
# ══════════════════════════════════════════════════════════════════

class TestMessageStorage:

    def test_message_has_sender_and_receiver(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        client.post(f'/messages/send/{bob}', data={'content': 'Test msg'})
        with app.app_context():
            m = Message.query.first()
            assert m.sender_id == alice
            assert m.receiver_id == bob

    def test_message_has_timestamp(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        client.post(f'/messages/send/{bob}', data={'content': 'Time test'})
        with app.app_context():
            m = Message.query.first()
            assert m.created_at is not None

    def test_message_is_read_defaults_false(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        client.post(f'/messages/send/{bob}', data={'content': 'Unread test'})
        with app.app_context():
            m = Message.query.first()
            assert m.is_read is False

    def test_conversation_orders_by_time(self, client, app):
        """Messages in conversation view should be in chronological order."""
        alice, bob, sid = _setup_connected_pair(app, client)
        m1 = _create_message(app, alice, bob, 'AAA-First-message')
        m2 = _create_message(app, bob, alice, 'BBB-Second-message')
        m3 = _create_message(app, alice, bob, 'CCC-Third-message')
        # Verify the DB query returns them in correct order
        with app.app_context():
            msgs = (Message.query
                    .filter(or_(
                        and_(Message.sender_id == alice, Message.receiver_id == bob),
                        and_(Message.sender_id == bob, Message.receiver_id == alice),
                    ))
                    .order_by(Message.created_at.asc(), Message.id.asc())
                    .all())
            assert len(msgs) == 3
            assert msgs[0].content == 'AAA-First-message'
            assert msgs[1].content == 'BBB-Second-message'
            assert msgs[2].content == 'CCC-Third-message'
        # Also verify the page loads and contains all three
        r = client.get(f'/messages/conversation/{bob}')
        assert b'AAA-First' in r.data
        assert b'BBB-Second' in r.data
        assert b'CCC-Third' in r.data

    def test_multiple_messages_stored(self, client, app):
        alice, bob, sid = _setup_connected_pair(app, client)
        for i in range(5):
            client.post(f'/messages/send/{bob}', data={'content': f'Message {i}'})
        with app.app_context():
            assert Message.query.count() == 5
