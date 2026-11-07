"""
models.py - SQLAlchemy database models for SkillSwap platform.
Defines all tables: users, skills, exchange_requests, messages, reviews, notifications.

Role system
-----------
  is_admin = False  →  normal student
  is_admin = True,  role = 'admin'        →  platform admin
  is_admin = True,  role = 'super_admin'  →  super admin (full privileges)

The `role` column was added with ALTER TABLE (safe migration) so existing
rows default to NULL, which is treated as 'admin' by all code paths.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ─────────────────────────────────────────────
# Association table: user ↔ skills they TEACH
# ─────────────────────────────────────────────
user_teaching_skills = db.Table(
    'user_teaching_skills',
    db.Column('user_id',  db.Integer, db.ForeignKey('users.id'),  primary_key=True),
    db.Column('skill_id', db.Integer, db.ForeignKey('skills.id'), primary_key=True),
    db.Column('proficiency', db.String(20), default='Intermediate')  # Beginner / Intermediate / Expert
)

# ─────────────────────────────────────────────
# Association table: user ↔ skills they LEARN
# ─────────────────────────────────────────────
user_learning_skills = db.Table(
    'user_learning_skills',
    db.Column('user_id',  db.Integer, db.ForeignKey('users.id'),  primary_key=True),
    db.Column('skill_id', db.Integer, db.ForeignKey('skills.id'), primary_key=True)
)


# ─────────────────────────────────────────────
# User model
# ─────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    college       = db.Column(db.String(200))
    branch        = db.Column(db.String(100))
    year          = db.Column(db.String(20))           # e.g. "2nd Year"
    bio           = db.Column(db.Text)
    profile_photo = db.Column(db.String(300), default='default_avatar.png')
    experience    = db.Column(db.String(50), default='Beginner')  # Beginner/Intermediate/Expert
    is_admin      = db.Column(db.Boolean, default=False)
    # role is only meaningful when is_admin=True.
    # Values: None / 'admin' → standard admin
    #         'super_admin'  → full super-admin privileges
    # NULL is treated identically to 'admin' everywhere in the codebase.
    role          = db.Column(db.String(30), default=None)
    is_active     = db.Column(db.Boolean, default=True)
    is_reported   = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen     = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    teaching_skills = db.relationship(
        'Skill', secondary=user_teaching_skills,
        backref=db.backref('teachers', lazy='dynamic'), lazy='dynamic'
    )
    learning_skills = db.relationship(
        'Skill', secondary=user_learning_skills,
        backref=db.backref('learners', lazy='dynamic'), lazy='dynamic'
    )
    # Sent / received exchange requests
    sent_requests     = db.relationship('ExchangeRequest', foreign_keys='ExchangeRequest.sender_id',
                                        backref='sender', lazy='dynamic')
    received_requests = db.relationship('ExchangeRequest', foreign_keys='ExchangeRequest.receiver_id',
                                        backref='receiver', lazy='dynamic')
    # Messages
    sent_messages     = db.relationship('Message', foreign_keys='Message.sender_id',
                                        backref='sender', lazy='dynamic')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id',
                                        backref='receiver', lazy='dynamic')
    # Reviews given / received
    reviews_given    = db.relationship('Review', foreign_keys='Review.reviewer_id',
                                       backref='reviewer', lazy='dynamic')
    reviews_received = db.relationship('Review', foreign_keys='Review.reviewee_id',
                                       backref='reviewee', lazy='dynamic')
    # Notifications
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    # ── password helpers ──────────────────────
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ── computed properties ───────────────────
    @property
    def is_super_admin(self) -> bool:
        """True only for the super_admin role."""
        return bool(self.is_admin and self.role == 'super_admin')
    @property
    def avg_rating(self):
        reviews = self.reviews_received.all()
        if not reviews:
            return 0.0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    @property
    def total_exchanges(self):
        return ExchangeRequest.query.filter(
            ((ExchangeRequest.sender_id == self.id) | (ExchangeRequest.receiver_id == self.id)),
            ExchangeRequest.status == 'completed'
        ).count()

    @property
    def active_exchanges(self):
        return ExchangeRequest.query.filter(
            ((ExchangeRequest.sender_id == self.id) | (ExchangeRequest.receiver_id == self.id)),
            ExchangeRequest.status == 'accepted'
        ).count()

    @property
    def pending_requests_count(self):
        return self.received_requests.filter_by(status='pending').count()

    @property
    def unread_notifications(self):
        return self.notifications.filter_by(is_read=False).count()

    def __repr__(self):
        return f'<User {self.email}>'


# ─────────────────────────────────────────────
# Skill model
# ─────────────────────────────────────────────
class Skill(db.Model):
    __tablename__ = 'skills'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), unique=True, nullable=False)
    category    = db.Column(db.String(80))   # e.g. Programming, Music, Language
    description = db.Column(db.Text)
    icon        = db.Column(db.String(60), default='fa-star')  # Font Awesome icon class
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Skill {self.name}>'


# ─────────────────────────────────────────────
# Exchange Request model
# ─────────────────────────────────────────────
class ExchangeRequest(db.Model):
    __tablename__ = 'exchange_requests'

    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # Which skill the sender wants to learn from receiver
    skill_requested_id = db.Column(db.Integer, db.ForeignKey('skills.id'))
    # Which skill the sender offers to teach
    skill_offered_id   = db.Column(db.Integer, db.ForeignKey('skills.id'))
    message     = db.Column(db.Text)          # optional intro message
    status      = db.Column(db.String(20), default='pending')  # pending/accepted/rejected/completed/cancelled
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    skill_requested = db.relationship('Skill', foreign_keys=[skill_requested_id])
    skill_offered   = db.relationship('Skill', foreign_keys=[skill_offered_id])

    def __repr__(self):
        return f'<ExchangeRequest {self.sender_id}->{self.receiver_id} [{self.status}]>'


# ─────────────────────────────────────────────
# Message model  (enhanced with soft-delete & attachment support)
# ─────────────────────────────────────────────
class Message(db.Model):
    __tablename__ = 'messages'

    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content     = db.Column(db.Text, nullable=False)
    msg_type    = db.Column(db.String(20), default='text')   # text / image / audio
    is_read     = db.Column(db.Boolean, default=False)
    # Soft-delete flags — never physically removed from DB
    deleted_by_sender   = db.Column(db.Boolean, default=False)
    deleted_by_receiver = db.Column(db.Boolean, default=False)
    deleted_for_all     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    # Attachment (one per message — NULL for text messages)
    attachment = db.relationship(
        'MessageAttachment', backref='message',
        uselist=False, lazy='joined',
        cascade='all, delete-orphan'
    )

    def is_visible_to(self, user_id: int) -> bool:
        """Return False if this message was soft-deleted for *user_id*."""
        if self.deleted_for_all:
            return False
        if user_id == self.sender_id and self.deleted_by_sender:
            return False
        if user_id == self.receiver_id and self.deleted_by_receiver:
            return False
        return True

    def __repr__(self):
        return f'<Message {self.sender_id}->{self.receiver_id}>'


# ─────────────────────────────────────────────
# MessageAttachment  (images & audio files)
# ─────────────────────────────────────────────
class MessageAttachment(db.Model):
    __tablename__ = 'message_attachments'

    id         = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    filename   = db.Column(db.String(300), nullable=False)   # stored filename (UUID)
    original   = db.Column(db.String(300))                   # original upload name
    mime_type  = db.Column(db.String(100))
    file_size  = db.Column(db.Integer)                       # bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Attachment msg={self.message_id} {self.filename}>'


# ─────────────────────────────────────────────
# CallHistory  (audio + video call records)
# ─────────────────────────────────────────────
class CallHistory(db.Model):
    __tablename__ = 'call_history'

    id          = db.Column(db.Integer, primary_key=True)
    caller_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    callee_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    call_type   = db.Column(db.String(10), default='audio')  # audio / video
    status      = db.Column(db.String(20), default='missed') # calling/accepted/rejected/missed/ended
    started_at  = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at    = db.Column(db.DateTime)
    duration_s  = db.Column(db.Integer, default=0)          # seconds

    caller = db.relationship('User', foreign_keys=[caller_id], backref='calls_made')
    callee = db.relationship('User', foreign_keys=[callee_id], backref='calls_received')

    def __repr__(self):
        return f'<Call {self.caller_id}->{self.callee_id} [{self.status}]>'


# ─────────────────────────────────────────────
# Review model
# ─────────────────────────────────────────────
class Review(db.Model):
    __tablename__ = 'reviews'

    id          = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exchange_id = db.Column(db.Integer, db.ForeignKey('exchange_requests.id'))
    rating      = db.Column(db.Integer, nullable=False)   # 1–5
    feedback    = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    exchange = db.relationship('ExchangeRequest', backref='reviews')

    def __repr__(self):
        return f'<Review {self.reviewer_id}→{self.reviewee_id} {self.rating}★>'


# ─────────────────────────────────────────────
# Notification model
# ─────────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notifications'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title      = db.Column(db.String(200))
    body       = db.Column(db.Text)
    link       = db.Column(db.String(300))      # URL to redirect on click
    icon       = db.Column(db.String(60), default='fa-bell')
    notif_type = db.Column(db.String(30), default='general')
    # Types: message, exchange_request, exchange_accepted,
    #        exchange_rejected, review, call_audio, call_video, general
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Notification {self.user_id} {self.title}>'
