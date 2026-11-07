"""
tests/test_matching.py
======================
Tests for the Smart Skill Matching Engine.

Covers:
  - Pure algorithm tests (100%, 50%, 0% matches)
  - Edge cases (no skills, empty sets, self-overlap)
  - Sorting (ranked by percentage descending)
  - Duplicate prevention (each candidate appears at most once)
  - Category filtering
  - Search by name / college
  - Minimum score filter
  - Full HTTP route integration tests

Matching formula:
    Match Percentage = (Matched Skill Directions / 2) * 100

    Direction 1: candidate teaches a skill I want to learn
    Direction 2: I teach a skill the candidate wants to learn

    Both match  → 100%  (mutual)
    One match   → 50%
    Neither     → 0%   (excluded from results)
"""

import pytest
from app import create_app
from app.models import db as _db, User, Skill
from app.services.matching_service import (
    SkillRef, MatchResult, compute_match, find_matches,
)


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
        _db.session.query(User).delete()
        _db.session.query(Skill).delete()
        from app.models import user_teaching_skills, user_learning_skills
        _db.session.execute(_db.text('DELETE FROM user_teaching_skills'))
        _db.session.execute(_db.text('DELETE FROM user_learning_skills'))
        _db.session.commit()
        _db.session.remove()
    yield


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────

def _skill(name, category='Programming'):
    """Create a SkillRef for algorithm-level tests."""
    return SkillRef(id=abs(hash(name)) % 10000, name=name, category=category)


def _make_skill(app, name, category='Programming'):
    """Create a Skill in the DB and return its id."""
    with app.app_context():
        s = Skill(name=name, category=category, icon='fa-code')
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _make_user(app, name, email, teaching_ids=None, learning_ids=None):
    """Create a User in the DB with optional skill associations."""
    from sqlalchemy import text
    with app.app_context():
        u = User(full_name=name, email=email, college='Test College')
        u.set_password('pass123')
        _db.session.add(u)
        _db.session.commit()
        uid = u.id
        for sid in (teaching_ids or []):
            _db.session.execute(
                text('INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                     'VALUES (:u, :s, :p)'),
                {'u': uid, 's': sid, 'p': 'Intermediate'}
            )
        for sid in (learning_ids or []):
            _db.session.execute(
                text('INSERT INTO user_learning_skills (user_id, skill_id) '
                     'VALUES (:u, :s)'),
                {'u': uid, 's': sid}
            )
        _db.session.commit()
        return uid


def _register_login(c, email='matcher@test.edu'):
    c.post('/auth/register', data={
        'full_name': 'Matcher User', 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
    }, follow_redirects=False)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


# ══════════════════════════════════════════════════════════════════
# 1. PURE ALGORITHM TESTS — compute_match()
# ══════════════════════════════════════════════════════════════════

class TestComputeMatch100Percent:

    def test_mutual_match_100(self):
        """
        Student A: teaches Python, learns UI/UX
        Student B: teaches UI/UX,  learns Python
        → 100% mutual match.
        """
        my_teach   = [_skill('Python', 'Programming')]
        my_learn   = [_skill('UI/UX Design', 'Design')]
        cand_teach = [_skill('UI/UX Design', 'Design')]
        cand_learn = [_skill('Python', 'Programming')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is not None
        assert result['score'] == 100
        assert result['matched_directions'] == 2

    def test_100_shows_mutual_reason(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Python')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert 'Mutual skill exchange' in result['reasons'][-1]

    def test_100_lists_both_directions(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Python')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert len(result['can_teach_me']) == 1
        assert result['can_teach_me'][0].name == 'Guitar'
        assert len(result['you_teach_them']) == 1
        assert result['you_teach_them'][0].name == 'Python'

    def test_100_multiple_skills_both_directions(self):
        """Multiple skills matching in both directions still = 100%."""
        my_teach   = [_skill('Python'), _skill('SQL')]
        my_learn   = [_skill('Guitar'), _skill('Spanish')]
        cand_teach = [_skill('Guitar'), _skill('Spanish')]
        cand_learn = [_skill('Python'), _skill('SQL')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result['score'] == 100
        assert result['matched_directions'] == 2
        assert len(result['can_teach_me']) == 2
        assert len(result['you_teach_them']) == 2


class TestComputeMatch50Percent:

    def test_one_way_their_teaching_to_my_learning_50(self):
        """
        Direction 1 only: candidate teaches Guitar, I want to learn Guitar.
        But I don't teach anything they want to learn.
        → 50%.
        """
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Cooking')]   # I don't teach Cooking

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is not None
        assert result['score'] == 50
        assert result['matched_directions'] == 1

    def test_one_way_my_teaching_to_their_learning_50(self):
        """
        Direction 2 only: I teach Python, candidate wants to learn Python.
        But candidate doesn't teach anything I want to learn.
        → 50%.
        """
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Cooking')]   # I don't want to learn Cooking
        cand_learn = [_skill('Python')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is not None
        assert result['score'] == 50
        assert result['matched_directions'] == 1

    def test_50_reason_does_not_mention_mutual(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Cooking')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        reasons_text = ' '.join(result['reasons'])
        assert 'Mutual' not in reasons_text
        assert 'Can teach you' in reasons_text

    def test_50_shows_only_matched_skills(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Cooking')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        # can_teach_me should have Guitar, you_teach_them should be empty
        assert len(result['can_teach_me']) == 1
        assert result['can_teach_me'][0].name == 'Guitar'
        assert len(result['you_teach_them']) == 0


class TestComputeMatch0Percent:

    def test_no_overlap_returns_none(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Cooking')]
        cand_learn = [_skill('Yoga')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is None

    def test_teaching_overlap_only_is_none(self):
        """If both users teach the same skill but neither learns the other's skill → 0%."""
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Python')]     # same teaching, not what I learn
        cand_learn = [_skill('Cooking')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is None

    def test_learning_overlap_only_is_none(self):
        """If both users want to learn the same skill but neither teaches it → 0%."""
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Cooking')]
        cand_learn = [_skill('Guitar')]     # same learning, not what I teach

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result is None


class TestComputeMatchEdgeCases:

    def test_both_empty_skills(self):
        result = compute_match([], [], [], [])
        assert result is None

    def test_i_have_no_skills(self):
        result = compute_match([], [], [_skill('Python')], [_skill('Guitar')])
        assert result is None

    def test_candidate_has_no_skills(self):
        result = compute_match([_skill('Python')], [_skill('Guitar')], [], [])
        assert result is None

    def test_partial_overlap_within_direction(self):
        """
        Multiple skills in each direction — only some overlap.
        Direction 1: candidate teaches {Guitar, Cooking}, I learn {Guitar, Yoga}
        → Guitar matches in direction 1.
        Direction 2: I teach {Python, SQL}, candidate learns {Python, Spanish}
        → Python matches in direction 2.
        → 100% mutual (both directions have at least one match).
        """
        my_teach   = [_skill('Python'), _skill('SQL')]
        my_learn   = [_skill('Guitar'), _skill('Yoga')]
        cand_teach = [_skill('Guitar'), _skill('Cooking')]
        cand_learn = [_skill('Python'), _skill('Spanish')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert result['score'] == 100
        assert result['matched_directions'] == 2
        assert len(result['can_teach_me']) == 1   # only Guitar
        assert result['can_teach_me'][0].name == 'Guitar'
        assert len(result['you_teach_them']) == 1  # only Python
        assert result['you_teach_them'][0].name == 'Python'

    def test_reasons_are_human_readable(self):
        my_teach   = [_skill('Python')]
        my_learn   = [_skill('Guitar')]
        cand_teach = [_skill('Guitar')]
        cand_learn = [_skill('Python')]

        result = compute_match(my_teach, my_learn, cand_teach, cand_learn)

        assert len(result['reasons']) == 3
        assert 'Can teach you' in result['reasons'][0]
        assert 'Guitar' in result['reasons'][0]
        assert 'Wants to learn from you' in result['reasons'][1]
        assert 'Python' in result['reasons'][1]
        assert 'Mutual' in result['reasons'][2]


# ══════════════════════════════════════════════════════════════════
# 2. find_matches() — full search with DB-backed users
# ══════════════════════════════════════════════════════════════════

class TestFindMatches:

    def test_excludes_current_user(self, app):
        """The logged-in user must never appear in their own match results."""
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])

        with app.app_context():
            me = User.query.get(my_uid)
            candidates = [me]   # only candidate is myself
            results = find_matches(me, candidates)
        assert results == []

    def test_no_duplicate_recommendations(self, app):
        """Each candidate appears at most once in the results."""
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        other_uid = _make_user(app, 'Other', 'other@test.edu',
                                teaching_ids=[guitar_id], learning_ids=[python_id])

        with app.app_context():
            me = User.query.get(my_uid)
            other = User.query.get(other_uid)
            # Pass the same candidate twice — should not produce duplicates
            results = find_matches(me, [other, other])

        assert len(results) == 1

    def test_ranked_by_percentage_descending(self, app):
        """100% matches appear before 50% matches."""
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        cooking_id = _make_skill(app, 'Cooking')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        # 100% match: teaches Guitar, learns Python
        uid_100 = _make_user(app, 'Perfect Match', 'perfect@test.edu',
                              teaching_ids=[guitar_id], learning_ids=[python_id])
        # 50% match: teaches Guitar, learns Cooking (only direction 1)
        uid_50 = _make_user(app, 'Half Match', 'half@test.edu',
                             teaching_ids=[guitar_id], learning_ids=[cooking_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_50), User.query.get(uid_100)]
            results = find_matches(me, cands)

        assert len(results) == 2
        assert results[0].score == 100
        assert results[0].user.full_name == 'Perfect Match'
        assert results[1].score == 50
        assert results[1].user.full_name == 'Half Match'

    def test_zero_percent_excluded(self, app):
        """Candidates with 0% match are not included in results."""
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        yoga_id   = _make_skill(app, 'Yoga')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        # No overlap: teaches Yoga, learns Cooking → not even created
        # 0%: teaches Yoga (I don't want), learns Yoga (I don't teach)
        uid_0 = _make_user(app, 'No Match', 'nomatch@test.edu',
                            teaching_ids=[yoga_id], learning_ids=[yoga_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_0)]
            results = find_matches(me, cands)

        assert results == []

    def test_user_with_no_skills_returns_empty(self, app):
        with app.app_context():
            u = User(full_name='Empty', email='empty@test.edu')
            u.set_password('pass123')
            _db.session.add(u)
            _db.session.commit()
            results = find_matches(u, [])
        assert results == []

    def test_category_filter(self, app):
        """Category filter should only show matches with skills in that category."""
        python_id = _make_skill(app, 'Python', 'Programming')
        guitar_id = _make_skill(app, 'Guitar', 'Music')
        spanish_id = _make_skill(app, 'Spanish', 'Language')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id],
                            learning_ids=[guitar_id, spanish_id])
        # Match 1: teaches Guitar (Music) — direction 1
        uid_guitar = _make_user(app, 'Guitar Teacher', 'guitar@test.edu',
                                 teaching_ids=[guitar_id], learning_ids=[])
        # Match 2: teaches Spanish (Language) — direction 1
        uid_spanish = _make_user(app, 'Spanish Teacher', 'spanish@test.edu',
                                  teaching_ids=[spanish_id], learning_ids=[])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_guitar), User.query.get(uid_spanish)]
            # Filter to Music category only
            results = find_matches(me, cands, category_filter='Music')

        assert len(results) == 1
        assert results[0].user.full_name == 'Guitar Teacher'

    def test_search_by_name(self, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        uid_a = _make_user(app, 'Alice Smith', 'alice@test.edu',
                            teaching_ids=[guitar_id], learning_ids=[python_id])
        uid_b = _make_user(app, 'Bob Jones', 'bob@test.edu',
                            teaching_ids=[guitar_id], learning_ids=[python_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_a), User.query.get(uid_b)]
            results = find_matches(me, cands, search_query='alice')

        assert len(results) == 1
        assert results[0].user.full_name == 'Alice Smith'

    def test_search_by_college(self, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        uid_iit = _make_user(app, 'IIT Student', 'iit@test.edu',
                              teaching_ids=[guitar_id], learning_ids=[python_id])
        # Override college
        with app.app_context():
            User.query.filter_by(email='iit@test.edu').update({'college': 'IIT Bombay'})
            _db.session.commit()

        uid_nit = _make_user(app, 'NIT Student', 'nit@test.edu',
                              teaching_ids=[guitar_id], learning_ids=[python_id])
        with app.app_context():
            User.query.filter_by(email='nit@test.edu').update({'college': 'NIT Surat'})
            _db.session.commit()

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_iit), User.query.get(uid_nit)]
            results = find_matches(me, cands, search_query='IIT')

        assert len(results) == 1
        assert 'IIT' in results[0].user.college

    def test_min_score_filter(self, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        cooking_id = _make_skill(app, 'Cooking')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        uid_100 = _make_user(app, 'Perfect', 'perfect@test.edu',
                              teaching_ids=[guitar_id], learning_ids=[python_id])
        uid_50 = _make_user(app, 'Half', 'half@test.edu',
                             teaching_ids=[guitar_id], learning_ids=[cooking_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_100), User.query.get(uid_50)]
            # Only show 100% matches
            results = find_matches(me, cands, min_score=100)

        assert len(results) == 1
        assert results[0].score == 100

    def test_shows_matched_skills(self, app):
        """MatchResult contains SkillRef objects for matched skills."""
        python_id = _make_skill(app, 'Python', 'Programming')
        guitar_id = _make_skill(app, 'Guitar', 'Music')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        uid_b = _make_user(app, 'Partner', 'partner@test.edu',
                            teaching_ids=[guitar_id], learning_ids=[python_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_b)]
            results = find_matches(me, cands)

        assert len(results) == 1
        r = results[0]
        assert len(r.can_teach_me) == 1
        assert r.can_teach_me[0].name == 'Guitar'
        assert r.can_teach_me[0].category == 'Music'
        assert len(r.you_teach_them) == 1
        assert r.you_teach_them[0].name == 'Python'

    def test_reasons_are_populated(self, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        my_uid = _make_user(app, 'Me', 'me@test.edu',
                            teaching_ids=[python_id], learning_ids=[guitar_id])
        uid_b = _make_user(app, 'Partner', 'partner@test.edu',
                            teaching_ids=[guitar_id], learning_ids=[python_id])

        with app.app_context():
            me = User.query.get(my_uid)
            cands = [User.query.get(uid_b)]
            results = find_matches(me, cands)

        assert len(results) == 1
        r = results[0]
        assert len(r.reasons) == 3  # can teach + wants to learn + mutual
        assert any('Guitar' in reason for reason in r.reasons)
        assert any('Python' in reason for reason in r.reasons)
        assert any('Mutual' in reason for reason in r.reasons)


# ══════════════════════════════════════════════════════════════════
# 3. HTTP ROUTE INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════

class TestMatchingRoute:

    def test_requires_login(self, client):
        r = client.get('/match/', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_no_skills_state(self, client):
        """User with no skills sees the 'add skills' prompt."""
        _register_login(client)
        r = client.get('/match/')
        assert r.status_code == 200
        assert b'Add skills' in r.data or b'add skills' in r.data.lower()

    def test_100_match_shown(self, client, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        _register_login(client)
        # Add skills for the logged-in user
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        # Create a 100% match candidate
        _make_user(app, 'Perfect Partner', 'perfect@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[python_id])

        r = client.get('/match/')
        assert r.status_code == 200
        assert b'Perfect Partner' in r.data
        assert b'100' in r.data

    def test_50_match_shown(self, client, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        cooking_id = _make_skill(app, 'Cooking')

        _register_login(client)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        # 50% match: teaches Guitar (direction 1), learns Cooking (not Python)
        _make_user(app, 'Half Partner', 'half@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[cooking_id])

        r = client.get('/match/')
        assert r.status_code == 200
        assert b'Half Partner' in r.data
        assert b'50' in r.data

    def test_0_match_excluded(self, client, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        yoga_id = _make_skill(app, 'Yoga')

        _register_login(client)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        # 0% match: teaches Yoga, learns Yoga — no overlap
        _make_user(app, 'Zero Partner', 'zero@test.edu',
                    teaching_ids=[yoga_id], learning_ids=[yoga_id])

        r = client.get('/match/')
        assert r.status_code == 200
        assert b'Zero Partner' not in r.data

    def test_search_filter(self, client, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')

        _register_login(client)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        _make_user(app, 'Alice Match', 'alice@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[python_id])
        _make_user(app, 'Bob Match', 'bob@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[python_id])

        r = client.get('/match/?q=Alice')
        assert r.status_code == 200
        assert b'Alice Match' in r.data
        assert b'Bob Match' not in r.data

    def test_category_filter(self, client, app):
        python_id = _make_skill(app, 'Python', 'Programming')
        guitar_id = _make_skill(app, 'Guitar', 'Music')

        _register_login(client)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        _make_user(app, 'Music Teacher', 'music@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[python_id])

        # Filter by Music category
        r = client.get('/match/?category=Music')
        assert r.status_code == 200
        assert b'Music Teacher' in r.data

        # Filter by a non-matching category
        r = client.get('/match/?category=Cooking')
        assert r.status_code == 200
        assert b'Music Teacher' not in r.data

    def test_min_score_filter(self, client, app):
        python_id = _make_skill(app, 'Python')
        guitar_id = _make_skill(app, 'Guitar')
        cooking_id = _make_skill(app, 'Cooking')

        _register_login(client)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='matcher@test.edu').first().id
            _db.session.execute(text(
                'INSERT INTO user_teaching_skills (user_id, skill_id, proficiency) '
                'VALUES (:u, :s, :p)'), {'u': uid, 's': python_id, 'p': 'Expert'})
            _db.session.execute(text(
                'INSERT INTO user_learning_skills (user_id, skill_id) '
                'VALUES (:u, :s)'), {'u': uid, 's': guitar_id})
            _db.session.commit()

        _make_user(app, 'Perfect', 'perfect@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[python_id])
        _make_user(app, 'Half', 'half@test.edu',
                    teaching_ids=[guitar_id], learning_ids=[cooking_id])

        # Only show 100% matches
        r = client.get('/match/?min_score=100')
        assert r.status_code == 200
        assert b'Perfect' in r.data
        assert b'Half' not in r.data
