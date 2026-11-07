"""
config.py - Application configuration settings for SkillSwap.

DATABASE PERSISTENCE GUARANTEE
───────────────────────────────
The SQLite database is stored at:
    <project_root>/skillswap.db

BASE_DIR is resolved with os.path.abspath(__file__) so it is always
an absolute path regardless of which directory Python is launched from.

db.create_all() (called in create_app) is SAFE — it only creates
tables that do not exist yet.  It NEVER drops, truncates or modifies
existing tables or rows.  Existing user accounts survive every restart.

To reset the database intentionally, delete skillswap.db manually,
then run:  python seed.py
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Permanent database path — always absolute, always the same file.
_DB_PATH = os.path.join(BASE_DIR, 'skillswap.db')


class Config:
    # ── Security ───────────────────────────────────────────────────
    # Override SECRET_KEY with a strong random value in production:
    #   export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
    SECRET_KEY = os.environ.get('SECRET_KEY', 'skillswap-secret-key-change-in-production')

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY  = True    # JS cannot read the cookie
    SESSION_COOKIE_SAMESITE  = 'Lax'  # CSRF protection
    SESSION_COOKIE_SECURE    = False   # Set True in production (HTTPS only)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days (remember-me)

    # ── Database ───────────────────────────────────────────────────
    # Uses the absolute path computed at module load time.
    # An environment variable DATABASE_URL overrides this for production.
    # db.create_all() is NON-DESTRUCTIVE — existing data is never deleted.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + _DB_PATH
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── File uploads ───────────────────────────────────────────────
    UPLOAD_FOLDER      = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024          # 5 MB max
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # ── Pagination ─────────────────────────────────────────────────
    STUDENTS_PER_PAGE = 12
    MESSAGES_PER_PAGE = 50

    # ── WebRTC / STUN / TURN ──────────────────────────────────────
    # STUN servers help discover public IP addresses for NAT traversal.
    # For production across different networks, a TURN server is required
    # to relay traffic when direct P2P fails.  Free public STUN servers
    # are listed below.  For TURN, deploy Coturn or use a hosted provider.
    WEBRTC_STUN_SERVERS = [
        {'urls': 'stun:stun.l.google.com:19302'},
        {'urls': 'stun:stun1.l.google.com:19302'},
    ]
    # TURN config — fill in your own TURN server credentials for production:
    WEBRTC_TURN_SERVERS = [
        # {'urls': 'turn:your.turn.server:3478',
        #  'username': 'user', 'credential': 'pass'},
    ]


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING                 = True
    DEBUG                   = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    # StaticPool forces a single shared connection so all app contexts
    # (fixtures + test client) see the same in-memory database.
    SQLALCHEMY_ENGINE_OPTIONS = {'poolclass': __import__('sqlalchemy.pool', fromlist=['StaticPool']).StaticPool}
    WTF_CSRF_ENABLED        = False
    SESSION_COOKIE_SECURE   = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True    # Enforce HTTPS-only cookies


config = {
    'development': DevelopmentConfig,
    'testing':     TestingConfig,
    'production':  ProductionConfig,
    'default':     DevelopmentConfig,
}
