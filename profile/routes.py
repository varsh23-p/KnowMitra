"""
profile/routes.py
=================
Student profile module — view, edit, browse, photo upload.

Key features:
  - View any student's profile (dynamically from DB)
  - Edit own profile with full server-side validation
  - Upload / replace profile photo with file validation
  - Browse all students with search + college filter + pagination
  - Old photo cleanup when a new one is uploaded
"""

import os
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from ..models import db, User, Review, ExchangeRequest

profile_bp = Blueprint('profile', __name__)

# ── Allowed values for dropdowns (server-side enforcement) ──────
ALLOWED_YEARS = {'1st Year', '2nd Year', '3rd Year', '4th Year',
                 '5th Year', 'Postgraduate'}
ALLOWED_EXPERIENCE = {'Beginner', 'Intermediate', 'Expert'}

# Max field lengths (must match model column sizes)
MAX_NAME    = 120
MAX_EMAIL   = 150
MAX_COLLEGE = 200
MAX_BRANCH  = 100
MAX_BIO     = 500


# ── File validation helpers ──────────────────────────────────────

def _allowed_file(filename):
    """Return True if the filename has an allowed image extension."""
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower()
            in current_app.config['ALLOWED_EXTENSIONS'])


def _is_real_image(file_storage):
    """
    Read the first few bytes and check the magic number.
    Prevents disguised executables renamed to .jpg.
    Returns True for known image signatures.
    """
    file_storage.stream.seek(0)
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)

    signatures = {
        b'\xff\xd8\xff':           'jpeg',
        b'\x89PNG\r\n\x1a\n':      'png',
        b'GIF87a':                  'gif',
        b'GIF89a':                  'gif',
        b'RIFF':                    'webp',   # RIFF....WEBP
    }
    for sig, fmt in signatures.items():
        if header.startswith(sig):
            return True
    return False


def _save_photo(file_storage, user_id):
    """Save an uploaded photo and return the stored filename."""
    import time, uuid
    # Build a safe, unique filename: user_id + float timestamp + short uuid
    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    ts  = str(time.time()).replace('.', '')
    uid  = uuid.uuid4().hex[:6]
    safe_name = f"user_{user_id}_{ts}_{uid}_photo.{ext}"
    file_storage.save(os.path.join(current_app.config['UPLOAD_FOLDER'], safe_name))
    return safe_name


def _delete_old_photo(filename):
    """Delete a previously uploaded photo file if it's not the default."""
    if not filename or filename == 'default_avatar.png':
        return
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass   # best-effort — don't crash the request


# ── View any student's profile ───────────────────────────────────

@profile_bp.route('/<int:user_id>')
@login_required
def view(user_id):
    """Render a student's profile page, pulling all data from the DB."""
    student = User.query.get_or_404(user_id)

    reviews = (Review.query
               .filter_by(reviewee_id=user_id)
               .order_by(Review.created_at.desc())
               .limit(10).all())

    # Check for an existing active exchange between the two users
    existing = ExchangeRequest.query.filter(
        ((ExchangeRequest.sender_id == current_user.id) &
         (ExchangeRequest.receiver_id == user_id)) |
        ((ExchangeRequest.sender_id == user_id) &
         (ExchangeRequest.receiver_id == current_user.id))
    ).filter(ExchangeRequest.status.in_(['pending', 'accepted'])).first()

    return render_template('profile/view.html',
                           student=student,
                           reviews=reviews,
                           existing_request=existing)


# ── Edit own profile ────────────────────────────────────────────

@profile_bp.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    """GET  → show the edit form.  POST → validate and save."""

    if request.method == 'POST':
        full_name  = request.form.get('full_name', '').strip()
        college    = request.form.get('college', '').strip()
        branch     = request.form.get('branch', '').strip()
        year       = request.form.get('year', '').strip()
        bio        = request.form.get('bio', '').strip()
        experience = request.form.get('experience', 'Beginner')

        # ── Collect all validation errors ──────────────────────
        errors: list[str] = []

        # Full name — required, 2–120 chars
        if not full_name:
            errors.append('Full name is required.')
        elif len(full_name) < 2:
            errors.append('Full name must be at least 2 characters.')
        elif len(full_name) > MAX_NAME:
            errors.append(f'Full name cannot exceed {MAX_NAME} characters.')

        # College — optional, max 200
        if len(college) > MAX_COLLEGE:
            errors.append(f'College name cannot exceed {MAX_COLLEGE} characters.')

        # Branch — optional, max 100
        if len(branch) > MAX_BRANCH:
            errors.append(f'Branch cannot exceed {MAX_BRANCH} characters.')

        # Year — optional but must be from the allowed set if provided
        if year and year not in ALLOWED_YEARS:
            errors.append('Please select a valid academic year.')

        # Bio — optional, max 500
        if len(bio) > MAX_BIO:
            errors.append(f'Bio cannot exceed {MAX_BIO} characters.')

        # Experience — must be from allowed set
        if experience not in ALLOWED_EXPERIENCE:
            errors.append('Please select a valid experience level.')

        # ── Photo upload validation ────────────────────────────
        photo = request.files.get('profile_photo')
        new_photo_name = None

        if photo and photo.filename:
            # Extension check
            if not _allowed_file(photo.filename):
                errors.append(
                    'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP.'
                )
            # Magic-number check (is it really an image?)
            elif not _is_real_image(photo):
                errors.append(
                    'The uploaded file does not appear to be a valid image.'
                )
            else:
                # Save the photo now so validation errors don't lose it —
                # but only commit the DB reference if no other errors exist
                try:
                    new_photo_name = _save_photo(photo, current_user.id)
                except Exception:
                    errors.append('Failed to save the uploaded photo. Please try again.')

        # ── Return early on errors ─────────────────────────────
        if errors:
            for msg in errors:
                flash(msg, 'danger')
            # Clean up the temp photo if we saved one but other errors exist
            if new_photo_name:
                _delete_old_photo(new_photo_name)
            return redirect(url_for('profile.edit'))

        # ── Apply changes ──────────────────────────────────────
        current_user.full_name  = full_name
        current_user.college    = college or None
        current_user.branch     = branch  or None
        current_user.year       = year    or None
        current_user.bio        = bio     or None
        current_user.experience = experience

        # If a new photo was uploaded, delete the old one and set the new name
        if new_photo_name:
            old_photo = current_user.profile_photo
            current_user.profile_photo = new_photo_name
            _delete_old_photo(old_photo)

        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile.view', user_id=current_user.id))

    return render_template('profile/edit.html')


# ── Browse all students ──────────────────────────────────────────

@profile_bp.route('/browse')
@login_required
def browse():
    """Paginated list of all active non-admin students (excluding self)."""
    page    = request.args.get('page', 1, type=int)
    search  = request.args.get('q', '').strip()
    college = request.args.get('college', '').strip()

    query = (User.query
             .filter_by(is_admin=False, is_active=True)
             .filter(User.id != current_user.id))

    if search:
        query = query.filter(User.full_name.ilike(f'%{search}%'))
    if college:
        query = query.filter(User.college.ilike(f'%{college}%'))

    students = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=current_app.config['STUDENTS_PER_PAGE'],
        error_out=False
    )

    return render_template('profile/browse.html',
                           students=students, search=search, college=college)


# ── Account self-deletion ────────────────────────────────────────

@profile_bp.route('/delete-account', methods=['GET', 'POST'])
@login_required
def delete_account():
    """
    GET  → show confirmation page with password prompt.
    POST → verify password, soft-delete related records safely,
           then permanently delete the user row.

    Safety rules:
      - Admin accounts cannot be self-deleted via this route.
      - Password must be confirmed before deletion proceeds.
      - Only the current user's own records are touched.
      - Other users' data (messages, reviews, etc.) is preserved.
      - Exchange requests are cancelled, not deleted, so the
        other party's history is intact.
    """
    from flask_login import logout_user
    from ..models import (ExchangeRequest, Message, Notification,
                          Review, db)
    from sqlalchemy import text, or_, and_

    # Admins must use the admin panel, not self-delete here
    if current_user.is_admin:
        flash('Admin accounts cannot be deleted through this page.', 'warning')
        return redirect(url_for('profile.view', user_id=current_user.id))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        # ── Validate ────────────────────────────────────────────
        if confirm != 'DELETE':
            flash('You must type DELETE in the confirmation box.', 'danger')
            return render_template('profile/delete_account.html')

        if not current_user.check_password(password):
            flash('Incorrect password. Account deletion cancelled.', 'danger')
            return render_template('profile/delete_account.html')

        uid = current_user.id

        # ── Safely clean up related records ─────────────────────
        # 1. Cancel pending/accepted exchanges (don't delete them —
        #    the other party keeps their history)
        ExchangeRequest.query.filter(
            or_(ExchangeRequest.sender_id == uid,
                ExchangeRequest.receiver_id == uid),
            ExchangeRequest.status.in_(['pending', 'accepted'])
        ).update({'status': 'cancelled'}, synchronize_session=False)

        # 2. Delete only this user's own notifications
        Notification.query.filter_by(user_id=uid).delete()

        # 3. Delete this user's sent and received messages
        Message.query.filter(
            or_(Message.sender_id == uid, Message.receiver_id == uid)
        ).delete(synchronize_session=False)

        # 4. Remove skill associations
        db.session.execute(
            text('DELETE FROM user_teaching_skills WHERE user_id = :u'),
            {'u': uid}
        )
        db.session.execute(
            text('DELETE FROM user_learning_skills WHERE user_id = :u'),
            {'u': uid}
        )

        # 5. Nullify reviews (keep the review rows so the other
        #    student's received ratings stay on their profile,
        #    but detach from the deleted user)
        Review.query.filter_by(reviewer_id=uid).update(
            {'reviewer_id': None}, synchronize_session=False
        )

        # 6. Log out before deleting the user row
        logout_user()

        # 7. Delete the user record itself
        user = db.session.get(User, uid)
        if user:
            db.session.delete(user)

        db.session.commit()

        flash('Your account has been permanently deleted. '
              'We hope to see you again!', 'info')
        return redirect(url_for('main.index'))

    return render_template('profile/delete_account.html')
