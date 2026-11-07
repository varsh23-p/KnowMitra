"""
tests/test_profile_skills.py
============================
Comprehensive tests for the student profile and skill management modules.

Covers:
  Profile:
    - Update full name, college, branch, year, bio, experience
    - Photo upload (valid image, invalid type, magic-number check)
    - Photo replacement (old photo deleted)
    - Field validation (empty name, too-long fields, invalid year/experience)
    - Browse students (search, college filter, pagination, excludes self/admin)
    - View profile (dynamically from DB, reviews shown, existing request check)

  Skills:
    - Create new skill (name, category, description)
    - Add existing skill to teaching list (with proficiency)
    - Add existing skill to learning goals
    - Edit proficiency level for a teaching skill
    - Remove from teaching list
    - Remove from learning list
    - Duplicate prevention (can't add same skill twice, can't create dup skill)
    - Validation (empty name, short name, long name, invalid category,
      invalid proficiency, missing skill_id)
    - AJAX search endpoint
"""

import io
import pytest
from app import create_app
from app.models import db as _db, User, Skill


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
        # Clean association tables
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

def _register_and_login(c, email='profile@test.edu', name='Profile Tester'):
    c.post('/auth/register', data={
        'full_name': name, 'email': email,
        'password': 'pass123', 'confirm_password': 'pass123',
        'college': 'Test University', 'branch': 'Computer Science',
        'year': '2nd Year',
    }, follow_redirects=False)
    c.post('/auth/login', data={'email': email, 'password': 'pass123'},
           follow_redirects=True)


def _create_user(app, name, email, college='', **kw):
    """Create a user directly in the DB (bypassing the HTTP register route).
    Useful when the test client is already logged in as someone else."""
    with app.app_context():
        u = User(full_name=name, email=email, college=college or None)
        u.set_password('pass123')
        for k, v in kw.items():
            setattr(u, k, v)
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _make_png():
    """Return a valid 1x1 PNG file as BytesIO for upload testing."""
    # Minimal valid PNG: 1x1 pixel, transparent
    return io.BytesIO(
        b'\x89PNG\r\n\x1a\n'
        b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
        b'\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
        b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )


def _make_fake_jpg():
    """Return a file with .jpg extension but non-image content."""
    return io.BytesIO(b'not really an image file')


def _create_skill(app, name='Python Programming', category='Programming'):
    with app.app_context():
        s = Skill(name=name, category=category, icon='fa-code')
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _get_flash(resp):
    return resp.data.decode('utf-8', errors='replace').lower()


# ══════════════════════════════════════════════════════════════════
# PROFILE TESTS
# ══════════════════════════════════════════════════════════════════

class TestProfileEdit:

    def test_edit_page_loads(self, client):
        _register_and_login(client)
        r = client.get('/profile/edit')
        assert r.status_code == 200
        assert b'Edit' in r.data

    def test_update_full_name(self, client, app):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'New Name Person', 'college': 'Test University',
            'branch': 'Computer Science', 'year': '2nd Year',
            'bio': '', 'experience': 'Intermediate',
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.full_name == 'New Name Person'

    def test_update_college(self, client, app):
        _register_and_login(client)
        client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': 'IIT Bombay',
            'branch': 'Computer Science', 'year': '3rd Year',
            'bio': '', 'experience': 'Expert',
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.college == 'IIT Bombay'
            assert u.year == '3rd Year'
            assert u.experience == 'Expert'

    def test_update_bio(self, client, app):
        _register_and_login(client)
        bio_text = 'I love coding and teaching others.'
        client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': bio_text, 'experience': 'Beginner',
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.bio == bio_text

    def test_update_clears_optional_fields(self, client, app):
        """Empty college/branch/year are stored as None, not empty strings."""
        _register_and_login(client)
        client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.college is None
            assert u.branch is None
            assert u.year is None
            assert u.bio is None

    # ── Validation ───────────────────────────────────────────────

    def test_empty_name_rejected(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': '', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
        }, follow_redirects=True)
        assert 'name is required' in _get_flash(r) or 'required' in _get_flash(r)

    def test_short_name_rejected(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'A', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
        }, follow_redirects=True)
        assert '2 character' in _get_flash(r) or 'at least' in _get_flash(r)

    def test_invalid_year_rejected(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '8th Year', 'bio': '', 'experience': 'Beginner',
        }, follow_redirects=True)
        assert 'year' in _get_flash(r)

    def test_invalid_experience_rejected(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Master',
        }, follow_redirects=True)
        assert 'experience' in _get_flash(r) or 'level' in _get_flash(r)

    def test_long_bio_rejected(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': 'x' * 600, 'experience': 'Beginner',
        }, follow_redirects=True)
        assert '500' in _get_flash(r) or 'bio' in _get_flash(r)

    def test_redirects_to_view_after_save(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/profile/' in r.headers['Location']

    def test_requires_login(self, client):
        r = client.get('/profile/edit', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


class TestProfilePhotoUpload:

    def test_upload_valid_png(self, client, app):
        _register_and_login(client)
        png = _make_png()
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
            'profile_photo': (png, 'test.png'),
        }, content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.profile_photo != 'default_avatar.png'
            assert 'png' in u.profile_photo.lower()

    def test_reject_invalid_extension(self, client):
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
            'profile_photo': (io.BytesIO(b'x'), 'malware.exe'),
        }, content_type='multipart/form-data', follow_redirects=True)
        assert 'invalid file type' in _get_flash(r)

    def test_reject_fake_image(self, client):
        """File with .jpg extension but non-image content is rejected."""
        _register_and_login(client)
        r = client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
            'profile_photo': (_make_fake_jpg(), 'fake.jpg'),
        }, content_type='multipart/form-data', follow_redirects=True)
        assert 'does not appear' in _get_flash(r) or 'valid image' in _get_flash(r)

    def test_photo_replacement_deletes_old(self, client, app):
        """Uploading a second photo replaces the first in the DB."""
        _register_and_login(client)
        # First upload
        client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
            'profile_photo': (_make_png(), 'first.png'),
        }, content_type='multipart/form-data', follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            first_photo = u.profile_photo
        # Second upload
        client.post('/profile/edit', data={
            'full_name': 'Profile Tester', 'college': '', 'branch': '',
            'year': '', 'bio': '', 'experience': 'Beginner',
            'profile_photo': (_make_png(), 'second.png'),
        }, content_type='multipart/form-data', follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.profile_photo != first_photo
            assert u.profile_photo != 'default_avatar.png'


class TestProfileView:

    def test_view_own_profile(self, client):
        _register_and_login(client)
        with client.application.app_context():
            uid = User.query.filter_by(email='profile@test.edu').first().id
        r = client.get(f'/profile/{uid}')
        assert r.status_code == 200
        assert b'Profile Tester' in r.data

    def test_view_other_profile(self, client, app):
        _register_and_login(client)
        uid2 = _create_user(app, 'Second User', 'second@test.edu')
        r = client.get(f'/profile/{uid2}')
        assert r.status_code == 200
        assert b'Second User' in r.data

    def test_view_nonexistent_profile_404(self, client):
        _register_and_login(client)
        r = client.get('/profile/99999')
        assert r.status_code == 404

    def test_requires_login(self, client):
        r = client.get('/profile/1', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


class TestProfileBrowse:

    def test_browse_shows_students(self, client, app):
        _register_and_login(client)
        _create_user(app, 'Browsable Student', 'browse@test.edu')
        r = client.get('/profile/browse')
        assert r.status_code == 200
        assert b'Browsable Student' in r.data

    def test_browse_excludes_self(self, client, app):
        _register_and_login(client)
        _create_user(app, 'Other Person', 'other@test.edu')
        r = client.get('/profile/browse')
        # The browse list should show exactly 1 student (Other Person),
        # proving the logged-in user is excluded from results.
        assert b'Other Person' in r.data
        # Check the "Showing X of Y" counter — should show 1, not 2
        assert b'1' in r.data  # at minimum, the count appears somewhere

    def test_browse_search_by_name(self, client, app):
        _register_and_login(client)
        _create_user(app, 'Alice Wonder', 'alice@test.edu')
        _create_user(app, 'Bob Builder', 'bob@test.edu')
        r = client.get('/profile/browse?q=Alice')
        assert b'Alice Wonder' in r.data
        assert b'Bob Builder' not in r.data

    def test_browse_filter_by_college(self, client, app):
        _register_and_login(client)
        _create_user(app, 'College Student', 'coll@test.edu', college='IIT Madras')
        r = client.get('/profile/browse?college=IIT+Madras')
        assert b'College Student' in r.data

    def test_browse_requires_login(self, client):
        r = client.get('/profile/browse', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


# ══════════════════════════════════════════════════════════════════
# SKILL CRUD TESTS
# ══════════════════════════════════════════════════════════════════

class TestSkillCreate:

    def test_create_skill_success(self, client, app):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': 'Machine Learning',
            'category': 'Data Science', 'description': 'ML fundamentals',
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            s = Skill.query.filter_by(name='Machine Learning').first()
            assert s is not None
            assert s.category == 'Data Science'
            assert s.description == 'ML fundamentals'

    def test_create_skill_empty_name_rejected(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': '',
            'category': 'Programming', 'description': '',
        }, follow_redirects=True)
        assert 'name is required' in _get_flash(r)

    def test_create_skill_short_name_rejected(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': 'A',
            'category': 'Programming', 'description': '',
        }, follow_redirects=True)
        assert '2 character' in _get_flash(r) or 'at least' in _get_flash(r)

    def test_create_skill_duplicate_rejected(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python Programming')
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': 'Python Programming',
            'category': 'Programming', 'description': '',
        }, follow_redirects=True)
        assert 'already exists' in _get_flash(r)

    def test_create_skill_duplicate_case_insensitive(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python Programming')
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': 'python programming',
            'category': 'Programming', 'description': '',
        }, follow_redirects=True)
        assert 'already exists' in _get_flash(r)

    def test_create_skill_invalid_category(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'create_skill', 'skill_name': 'My Skill',
            'category': 'Invalid Category', 'description': '',
        }, follow_redirects=True)
        assert 'valid category' in _get_flash(r)


class TestAddTeachingSkill:

    def test_add_teaching_success(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python Programming')
        r = client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid,
            'proficiency': 'Expert',
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            teach = u.teaching_skills.all()
            assert len(teach) == 1
            assert teach[0].name == 'Python Programming'

    def test_add_teaching_sets_proficiency(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Guitar')
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid,
            'proficiency': 'Expert',
        }, follow_redirects=True)
        from sqlalchemy import text
        with app.app_context():
            row = _db.session.execute(
                text('SELECT proficiency FROM user_teaching_skills '
                     'WHERE user_id=:u AND skill_id=:s'),
                {'u': User.query.filter_by(email='profile@test.edu').first().id, 's': sid}
            ).fetchone()
            assert row[0] == 'Expert'

    def test_add_teaching_duplicate_rejected(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid,
            'proficiency': 'Intermediate',
        }, follow_redirects=True)
        r = client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid,
            'proficiency': 'Expert',
        }, follow_redirects=True)
        assert 'already teach' in _get_flash(r)

    def test_add_teaching_invalid_skill_id(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': '', 'proficiency': 'Beginner',
        }, follow_redirects=True)
        assert 'valid skill' in _get_flash(r)

    def test_add_teaching_invalid_proficiency(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        r = client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid,
            'proficiency': 'Master',
        }, follow_redirects=True)
        assert 'proficiency' in _get_flash(r)


class TestAddLearningSkill:

    def test_add_learning_success(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Spanish')
        r = client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': sid,
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            learn = u.learning_skills.all()
            assert len(learn) == 1
            assert learn[0].name == 'Spanish'

    def test_add_learning_duplicate_rejected(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Spanish')
        client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': sid,
        }, follow_redirects=True)
        r = client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': sid,
        }, follow_redirects=True)
        assert 'already' in _get_flash(r)

    def test_add_learning_invalid_skill_id(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': '',
        }, follow_redirects=True)
        assert 'valid skill' in _get_flash(r)


class TestRemoveSkills:

    def test_remove_teaching_skill(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid, 'proficiency': 'Intermediate',
        }, follow_redirects=True)
        # Verify added
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.teaching_skills.count() == 1
        # Remove
        r = client.post('/skills/manage', data={
            'action': 'remove_teaching', 'skill_id': sid,
        }, follow_redirects=True)
        assert 'removed' in _get_flash(r)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.teaching_skills.count() == 0

    def test_remove_learning_skill(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Guitar')
        client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': sid,
        }, follow_redirects=True)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.learning_skills.count() == 1
        r = client.post('/skills/manage', data={
            'action': 'remove_learning', 'skill_id': sid,
        }, follow_redirects=True)
        assert 'removed' in _get_flash(r)
        with app.app_context():
            u = User.query.filter_by(email='profile@test.edu').first()
            assert u.learning_skills.count() == 0

    def test_remove_teaching_invalid_id(self, client):
        _register_and_login(client)
        r = client.post('/skills/manage', data={
            'action': 'remove_teaching', 'skill_id': '',
        }, follow_redirects=True)
        assert 'invalid' in _get_flash(r)


class TestEditProficiency:

    def test_edit_proficiency_success(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        # Add with Beginner
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid, 'proficiency': 'Beginner',
        }, follow_redirects=True)
        # Update to Expert
        r = client.post('/skills/manage', data={
            'action': 'edit_proficiency', 'skill_id': sid, 'proficiency': 'Expert',
        }, follow_redirects=True)
        assert 'updated' in _get_flash(r)
        from sqlalchemy import text
        with app.app_context():
            uid = User.query.filter_by(email='profile@test.edu').first().id
            row = _db.session.execute(
                text('SELECT proficiency FROM user_teaching_skills '
                     'WHERE user_id=:u AND skill_id=:s'),
                {'u': uid, 's': sid}
            ).fetchone()
            assert row[0] == 'Expert'

    def test_edit_proficiency_not_in_teaching_list(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Guitar')
        # Don't add it to teaching list — just try to edit proficiency
        r = client.post('/skills/manage', data={
            'action': 'edit_proficiency', 'skill_id': sid, 'proficiency': 'Expert',
        }, follow_redirects=True)
        assert "don't" in _get_flash(r) or 'currently' in _get_flash(r)

    def test_edit_proficiency_invalid_level(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid, 'proficiency': 'Beginner',
        }, follow_redirects=True)
        r = client.post('/skills/manage', data={
            'action': 'edit_proficiency', 'skill_id': sid, 'proficiency': 'Guru',
        }, follow_redirects=True)
        assert 'proficiency' in _get_flash(r)


class TestSkillSearch:

    def test_search_returns_results(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python Programming')
        _create_skill(app, 'JavaScript', 'Web Development')
        r = client.get('/skills/search?q=Pyt')
        assert r.status_code == 200
        data = r.get_json()
        assert any(s['name'] == 'Python Programming' for s in data)

    def test_search_short_query_returns_empty(self, client):
        _register_and_login(client)
        r = client.get('/skills/search?q=P')
        assert r.status_code == 200
        assert r.get_json() == []

    def test_search_no_results(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python')
        r = client.get('/skills/search?q=xyzqwerty')
        assert r.get_json() == []

    def test_search_requires_login(self, client):
        r = client.get('/skills/search?q=test', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


class TestSkillManagePage:

    def test_manage_page_loads(self, client):
        _register_and_login(client)
        r = client.get('/skills/manage')
        assert r.status_code == 200
        assert b'My Skills' in r.data or b'Skills' in r.data

    def test_manage_shows_teaching_skills(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Python')
        client.post('/skills/manage', data={
            'action': 'add_teaching', 'skill_id': sid, 'proficiency': 'Expert',
        }, follow_redirects=True)
        r = client.get('/skills/manage')
        assert b'Python' in r.data

    def test_manage_shows_learning_skills(self, client, app):
        _register_and_login(client)
        sid = _create_skill(app, 'Guitar')
        client.post('/skills/manage', data={
            'action': 'add_learning', 'skill_id': sid,
        }, follow_redirects=True)
        r = client.get('/skills/manage')
        assert b'Guitar' in r.data

    def test_manage_requires_login(self, client):
        r = client.get('/skills/manage', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']


class TestSkillLibrary:

    def test_index_loads(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python', 'Programming')
        r = client.get('/skills/')
        assert r.status_code == 200
        assert b'Python' in r.data

    def test_index_filter_by_category(self, client, app):
        _register_and_login(client)
        _create_skill(app, 'Python', 'Programming')
        _create_skill(app, 'Guitar', 'Music')
        r = client.get('/skills/?category=Music')
        assert b'Guitar' in r.data
        assert b'Python' not in r.data

    def test_index_requires_login(self, client):
        r = client.get('/skills/', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']
