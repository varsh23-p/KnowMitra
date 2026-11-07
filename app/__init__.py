"""
app/__init__.py - Flask application factory.
Creates and configures the Flask app, registers blueprints, and initialises extensions.
"""

import os
from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
from .models import db, User
from config import config

socketio = SocketIO()   # initialised without app here; bound in create_app


login_manager = LoginManager()
login_manager.login_view          = 'auth.login'
login_manager.login_message       = 'Please sign in to access that page.'
login_manager.login_message_category = 'warning'
# Keep session alive for 30 days when "remember me" is ticked
login_manager.refresh_view        = 'auth.login'
login_manager.needs_refresh_message = 'Please re-authenticate to continue.'
login_manager.needs_refresh_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    """Load user from DB by primary key stored in session cookie."""
    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None


@login_manager.unauthorized_handler
def handle_unauthorized():
    """
    Custom 401 handler: redirect to login with the original URL preserved
    so users land back on the right page after signing in.
    """
    from flask import redirect, url_for, request, flash
    flash('Please sign in to access that page.', 'warning')
    return redirect(url_for('auth.login', next=request.path))


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # Ensure message media folder exists
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'messages'), exist_ok=True)

    # Initialise extensions
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app,
                      cors_allowed_origins='*',
                      async_mode='threading',
                      logger=False,
                      engineio_logger=False)

    # ── Register blueprints ──────────────────────────────────────
    from .auth.routes     import auth_bp
    from .profile.routes  import profile_bp
    from .skills.routes   import skills_bp
    from .matching.routes import matching_bp
    from .exchanges.routes import exchanges_bp
    from .messages.routes import messages_bp
    from .messages.events import register_socket_events
    from .reviews.routes  import reviews_bp
    from .dashboard.routes import dashboard_bp
    from .admin.routes    import admin_bp
    from .main            import main_bp
    from .cli             import cli_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,      url_prefix='/auth')
    app.register_blueprint(profile_bp,   url_prefix='/profile')
    app.register_blueprint(skills_bp,    url_prefix='/skills')
    app.register_blueprint(matching_bp,  url_prefix='/match')
    app.register_blueprint(exchanges_bp, url_prefix='/exchanges')
    app.register_blueprint(messages_bp,  url_prefix='/messages')
    # Register SocketIO events (must happen after socketio.init_app)
    register_socket_events(socketio)
    app.register_blueprint(reviews_bp,   url_prefix='/reviews')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(admin_bp,     url_prefix='/admin')
    app.register_blueprint(cli_bp)       # CLI commands only, no URL prefix

    # ── Create tables on first run ───────────────────────────────
    # db.create_all() is NON-DESTRUCTIVE.
    # It only creates tables that do not exist yet.
    # Existing tables and all their rows (users, skills, messages, etc.)
    # are NEVER modified, truncated or dropped.
    with app.app_context():
        db.create_all()

        # ── Safe migration: add `role` column if it doesn't exist ─
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        existing_cols = [c['name'] for c in inspector.get_columns('users')]
        if 'role' not in existing_cols:
            db.session.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(30)")
            )
            db.session.commit()

        # ── Safe migration: add new message columns ────────────────
        msg_cols = [c['name'] for c in inspector.get_columns('messages')]
        new_msg_cols = {
            'msg_type':            'ALTER TABLE messages ADD COLUMN msg_type VARCHAR(20) DEFAULT "text"',
            'deleted_by_sender':   'ALTER TABLE messages ADD COLUMN deleted_by_sender BOOLEAN DEFAULT 0',
            'deleted_by_receiver': 'ALTER TABLE messages ADD COLUMN deleted_by_receiver BOOLEAN DEFAULT 0',
            'deleted_for_all':     'ALTER TABLE messages ADD COLUMN deleted_for_all BOOLEAN DEFAULT 0',
        }
        for col_name, sql in new_msg_cols.items():
            if col_name not in msg_cols:
                db.session.execute(text(sql))
        db.session.commit()

        # ── Safe migration: add notif_type to notifications table ─
        notif_cols = [c['name'] for c in inspector.get_columns('notifications')]
        if 'notif_type' not in notif_cols:
            db.session.execute(
                text("ALTER TABLE notifications ADD COLUMN notif_type VARCHAR(30) DEFAULT 'general'")
            )
            db.session.commit()

    # ── Register custom error handlers ──────────────────────────
    from .errors import register_error_handlers
    register_error_handlers(app)

    return app
