"""
UWC Compass — Flask Application
A student-built platform for sharing UWC second-round essays.

Created by Muhammad Mehran Lone, Kashmir, India.
"""

import os
import json
import uuid
import secrets
import sqlite3
import random
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_from_directory, abort, g
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message

# ---------------------------------------------------------------------------
# App Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'uwc-compass-dev-key-change-in-production')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads', 'verification_images')
DOCUMENTS_FOLDER = os.path.join(BASE_DIR, 'uploads', 'documents')
VOLUNTEER_IDS_FOLDER = os.path.join(BASE_DIR, 'uploads', 'volunteer_ids')

ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DOCUMENTS_FOLDER'] = DOCUMENTS_FOLDER
app.config['VOLUNTEER_IDS_FOLDER'] = VOLUNTEER_IDS_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Flask-Mail config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER', 'dummy@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS', 'dummypass')
app.config['MAIL_DEFAULT_SENDER'] = ('UWC Compass', os.environ.get('EMAIL_USER', 'dummy@gmail.com'))

mail = Mail(app)

from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DOCUMENTS_FOLDER, exist_ok=True)
os.makedirs(VOLUNTEER_IDS_FOLDER, exist_ok=True)

MAX_WORDS_PER_ESSAY = 800
NUM_ESSAY_SLOTS = 7

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE = os.path.join(BASE_DIR, 'essays.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)

    db.execute('''
        CREATE TABLE IF NOT EXISTS essays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            national_committee TEXT NOT NULL,
            year_applied INTEGER NOT NULL,
            interview_status TEXT NOT NULL,
            email TEXT,
            essays_json TEXT NOT NULL,
            document_path TEXT,
            screenshot_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            flagged INTEGER NOT NULL DEFAULT 0,
            moderated_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS moderator_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            country TEXT NOT NULL,
            motivation TEXT NOT NULL,
            id_photo_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS volunteers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            access_key_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            application_id INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES moderator_applications(id)
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS blocked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            name TEXT,
            reason TEXT NOT NULL,
            blocked_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS moderation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            reason TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    db.execute('''
        CREATE TABLE IF NOT EXISTS email_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            essay_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(essay_id) REFERENCES essays(id)
        )
    ''')

    # Seed defaults
    cursor = db.execute('SELECT COUNT(*) FROM admins')
    if cursor.fetchone()[0] == 0:
        db.execute(
            'INSERT INTO admins (username, password_hash) VALUES (?, ?)',
            ('lonemehran', generate_password_hash('LONEMEHRAN8899'))
        )

    db.execute('INSERT OR IGNORE INTO site_settings (key, value) VALUES (?, ?)',
               ('maintenance_mode', 'false'))

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def allowed_document(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOCUMENT_EXTENSIONS


def validate_image(file_stream):
    try:
        from PIL import Image
        img = Image.open(file_stream)
        img.verify()
        file_stream.seek(0)
        return img.format.lower() in {'jpeg', 'png'}
    except Exception:
        file_stream.seek(0)
        return False


def save_file(file, folder):
    original = secure_filename(file.filename)
    if not original:
        return None
    ext = original.rsplit('.', 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(folder, unique_name)
    file.save(filepath)
    return unique_name


def is_maintenance_mode():
    db = get_db()
    row = db.execute("SELECT value FROM site_settings WHERE key = 'maintenance_mode'").fetchone()
    return row and row['value'] == 'true'


def is_blocked(name, email):
    db = get_db()
    if email:
        blocked = db.execute('SELECT id FROM blocked_users WHERE email = ?', (email,)).fetchone()
        if blocked:
            return True
    if name:
        blocked = db.execute('SELECT id FROM blocked_users WHERE name = ?', (name,)).fetchone()
        if blocked:
            return True
    return False


def log_action(actor, role, action, target_type, target_id=None, reason=None, details=None):
    db = get_db()
    db.execute('''
        INSERT INTO moderation_logs (actor, role, action, target_type, target_id, reason, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (actor, role, action, target_type, target_id, reason, details))
    db.commit()


# ---------------------------------------------------------------------------
# Auth Decorators
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


def volunteer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'volunteer':
            return redirect(url_for('volunteer_login'))
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    """Allow admin or volunteer."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ('admin', 'volunteer'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Template Helpers
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    maintenance = False
    try:
        maintenance = is_maintenance_mode()
    except Exception:
        pass
    return {
        'current_year': datetime.now().year,
        'num_essay_slots': NUM_ESSAY_SLOTS,
        'max_words_per_essay': MAX_WORDS_PER_ESSAY,
        'maintenance_mode': maintenance,
    }


@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Public Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM essays WHERE status = ?', ('approved',)).fetchone()[0]
    return render_template('index.html', essay_count=count)


@app.route('/submit', methods=['GET', 'POST'])
def submit():
    # Check maintenance mode
    if is_maintenance_mode():
        flash('Essay submissions are temporarily paused for site maintenance. Please check back later.', 'error')
        return render_template('submit.html',
                               name='', country='', national_committee='',
                               year_applied='', interview_status='',
                               email='', essays_list=[], submissions_paused=True)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        country = request.form.get('country', '').strip()
        national_committee = request.form.get('national_committee', '').strip()
        year_applied = request.form.get('year_applied', '').strip()
        interview_status = request.form.get('interview_status', '').strip()
        email = request.form.get('email', '').strip()
        screenshot = request.files.get('screenshot')
        document = request.files.get('document')

        # Check if user is blocked
        if is_blocked(name, email):
            flash('Your account has been blocked from submitting. Contact admin if you believe this is an error.', 'error')
            return redirect(url_for('submit'))

        essays_list = []
        for i in range(1, NUM_ESSAY_SLOTS + 1):
            prompt = request.form.get(f'prompt_{i}', '').strip()
            response = request.form.get(f'response_{i}', '').strip()
            if prompt or response:
                essays_list.append({'prompt': prompt, 'response': response})

        errors = []

        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not country:
            errors.append('Country is required.')
        if not national_committee:
            errors.append('National committee name is required.')
        if not year_applied or not year_applied.isdigit():
            errors.append('Year applied must be a valid year.')
        if interview_status not in ('yes', 'no', 'pending'):
            errors.append('Please select your interview status.')

        has_essays = any(e['response'] for e in essays_list)
        has_document = document and document.filename != ''

        if not has_essays and not has_document:
            errors.append('Please either type at least one essay or upload a document.')

        for i, essay in enumerate(essays_list):
            if essay['response']:
                wc = len(essay['response'].split())
                if wc > MAX_WORDS_PER_ESSAY:
                    errors.append(f'Essay {i + 1} exceeds {MAX_WORDS_PER_ESSAY} words ({wc} words).')

        if not screenshot or screenshot.filename == '':
            errors.append('Verification screenshot is required.')
        elif not allowed_image(screenshot.filename):
            errors.append('Screenshot must be JPG, JPEG, or PNG.')
        elif not validate_image(screenshot.stream):
            errors.append('Screenshot is not a valid image file.')

        doc_path = None
        if has_document:
            if not allowed_document(document.filename):
                errors.append('Document must be PDF, DOC, or DOCX.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('submit.html',
                                   name=name, country=country,
                                   national_committee=national_committee,
                                   year_applied=year_applied,
                                   interview_status=interview_status,
                                   email=email or '', essays_list=essays_list)

        screenshot_name = save_file(screenshot, app.config['UPLOAD_FOLDER'])
        if not screenshot_name:
            flash('Screenshot upload failed.', 'error')
            return render_template('submit.html',
                                   name=name, country=country,
                                   national_committee=national_committee,
                                   year_applied=year_applied,
                                   interview_status=interview_status,
                                   email=email or '', essays_list=essays_list)

        if has_document:
            doc_path = save_file(document, app.config['DOCUMENTS_FOLDER'])

        db = get_db()
        cursor = db.execute('''
            INSERT INTO essays
            (name, country, national_committee, year_applied, interview_status,
             email, essays_json, document_path, screenshot_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, country, national_committee, int(year_applied),
              interview_status, email, json.dumps(essays_list),
              doc_path, screenshot_name, 'unverified'))
        essay_id = cursor.lastrowid
        
        # Generate OTP
        otp_code = ''.join(random.choices(string.digits, k=6))
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        
        db.execute('''
            INSERT INTO email_verifications (essay_id, email, otp_code, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (essay_id, email, otp_code, expires_at))
        db.commit()

        # Send Email
        try:
            msg = Message('Verify your UWC Compass submission', recipients=[email])
            msg.body = f"Your Verification Code is: {otp_code}\n\nThis code will expire in 15 minutes."
            mail.send(msg)
        except Exception:
            # Fallback for dev environments without real SMTP
            print(f"MOCK EMAIL to {email}: Your Verification Code is {otp_code}")

        return redirect(url_for('verify_email', essay_id=essay_id))

    return render_template('submit.html',
                           name='', country='', national_committee='',
                           year_applied='', interview_status='',
                           email='', essays_list=[])


@app.route('/verify-email/<int:essay_id>', methods=['GET', 'POST'])
def verify_email(essay_id):
    db = get_db()
    essay = db.execute('SELECT * FROM essays WHERE id = ?', (essay_id,)).fetchone()
    if not essay or essay['status'] != 'unverified':
        flash('Invalid essay submission or already verified.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        otp = request.form.get('otp', '').strip()
        verification = db.execute('SELECT * FROM email_verifications WHERE essay_id = ? ORDER BY created_at DESC LIMIT 1', (essay_id,)).fetchone()
        
        if not verification:
            flash('No verification code found.', 'error')
            return redirect(url_for('verify_email', essay_id=essay_id))
            
        if otp == verification['otp_code']:
            db.execute("UPDATE essays SET status = 'pending' WHERE id = ?", (essay_id,))
            db.commit()
            flash('Email verified correctly! Your essays will appear publicly after moderator review.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid verification code. Please check your email.', 'error')
            
    return render_template('verify_email.html', email=essay['email'])


@app.route('/essays')
def essays():
    db = get_db()
    
    # Get filter parameters
    nc_filter = request.args.get('nc', '').strip()
    year_filter = request.args.get('year', '').strip()
    
    # Base query
    query = '''
        SELECT id, name, country, national_committee, year_applied,
               interview_status, essays_json, created_at
        FROM essays WHERE status = ?
    '''
    params = ['approved']
    
    if nc_filter:
        query += ' AND national_committee = ?'
        params.append(nc_filter)
    if year_filter:
        query += ' AND year_applied = ?'
        params.append(year_filter)
        
    query += ' ORDER BY created_at DESC'
    
    rows = db.execute(query, tuple(params)).fetchall()
    
    # Fetch unique filter options
    committees = db.execute('SELECT DISTINCT national_committee FROM essays WHERE status = ? ORDER BY national_committee', ('approved',)).fetchall()
    years = db.execute('SELECT DISTINCT year_applied FROM essays WHERE status = ? ORDER BY year_applied DESC', ('approved',)).fetchall()
    
    return render_template('essays.html', essays=rows, committees=[c[0] for c in committees], years=[y[0] for y in years], current_nc=nc_filter, current_year=year_filter)


@app.route('/essay/<int:essay_id>')
def essay_detail(essay_id):
    db = get_db()
    essay = db.execute('''
        SELECT id, name, country, national_committee, year_applied,
               interview_status, essays_json, document_path, created_at
        FROM essays WHERE id = ? AND status = ?
    ''', (essay_id, 'approved')).fetchone()
    if essay is None:
        abort(404)
    return render_template('essay_detail.html', essay=essay)


@app.route('/volunteer', methods=['GET', 'POST'])
def volunteer():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        country = request.form.get('country', '').strip()
        motivation = request.form.get('motivation', '').strip()
        id_photo = request.files.get('id_photo')

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not country:
            errors.append('Country is required.')
        if not motivation:
            errors.append('Motivation text is required.')
        if not id_photo or id_photo.filename == '':
            errors.append('Government ID photo is required.')
        elif not allowed_image(id_photo.filename):
            errors.append('ID photo must be JPG, JPEG, or PNG.')
        elif not validate_image(id_photo.stream):
            errors.append('ID photo is not a valid image file.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('volunteer.html',
                                   name=name, email=email, country=country, motivation=motivation)

        id_photo_path = save_file(id_photo, app.config['VOLUNTEER_IDS_FOLDER'])

        db = get_db()
        db.execute('''
            INSERT INTO moderator_applications (name, email, country, motivation, id_photo_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, email, country, motivation, id_photo_path, 'pending'))
        db.commit()

        flash('Thank you for volunteering! Your application will be reviewed by the admin.', 'success')
        return redirect(url_for('volunteer'))

    return render_template('volunteer.html', name='', email='', country='', motivation='')


@app.route('/contact')
def contact():
    return render_template('contact.html')


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        admin = db.execute('SELECT * FROM admins WHERE username = ?', (username,)).fetchone()

        if admin and check_password_hash(admin['password_hash'], password):
            session.clear()
            session['role'] = 'admin'
            session['username'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()

    pending_essays = db.execute(
        'SELECT * FROM essays WHERE status = ? ORDER BY created_at DESC', ('pending',)
    ).fetchall()
    approved_essays = db.execute(
        'SELECT * FROM essays WHERE status = ? ORDER BY created_at DESC', ('approved',)
    ).fetchall()
    rejected_essays = db.execute(
        'SELECT * FROM essays WHERE status = ? ORDER BY created_at DESC', ('rejected',)
    ).fetchall()
    flagged_essays = db.execute(
        'SELECT * FROM essays WHERE flagged = 1 ORDER BY created_at DESC'
    ).fetchall()

    pending_mods = db.execute(
        'SELECT * FROM moderator_applications WHERE status = ? ORDER BY created_at DESC', ('pending',)
    ).fetchall()
    processed_mods = db.execute(
        'SELECT * FROM moderator_applications WHERE status != ? ORDER BY created_at DESC', ('pending',)
    ).fetchall()

    active_volunteers = db.execute(
        'SELECT * FROM volunteers WHERE active = 1 ORDER BY created_at DESC'
    ).fetchall()

    blocked_users = db.execute(
        'SELECT * FROM blocked_users ORDER BY created_at DESC'
    ).fetchall()

    audit_logs = db.execute(
        'SELECT * FROM moderation_logs ORDER BY created_at DESC LIMIT 100'
    ).fetchall()

    maintenance = is_maintenance_mode()

    return render_template('admin.html',
                           pending_essays=pending_essays,
                           approved_essays=approved_essays,
                           rejected_essays=rejected_essays,
                           flagged_essays=flagged_essays,
                           pending_mods=pending_mods,
                           processed_mods=processed_mods,
                           active_volunteers=active_volunteers,
                           blocked_users=blocked_users,
                           audit_logs=audit_logs,
                           maintenance=maintenance)


@app.route('/admin/essay/<int:essay_id>/<action>', methods=['POST'])
@admin_required
def admin_essay_action(essay_id, action):
    if action not in ('approved', 'rejected'):
        abort(400)
    db = get_db()
    db.execute('UPDATE essays SET status = ?, moderated_by = ? WHERE id = ?',
               (action, session['username'], essay_id))
    db.commit()
    log_action(session['username'], 'admin', action, 'essay', essay_id)
    flash(f'Essay has been {action}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/essay/<int:essay_id>/delete', methods=['POST'])
@admin_required
def admin_essay_delete(essay_id):
    db = get_db()
    db.execute('DELETE FROM essays WHERE id = ?', (essay_id,))
    db.commit()
    log_action(session['username'], 'admin', 'deleted', 'essay', essay_id)
    flash('Essay permanently deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/essay/<int:essay_id>/flag', methods=['POST'])
@admin_required
def admin_essay_flag(essay_id):
    db = get_db()
    essay = db.execute('SELECT flagged FROM essays WHERE id = ?', (essay_id,)).fetchone()
    if essay is None:
        abort(404)
    new_flag = 0 if essay['flagged'] else 1
    db.execute('UPDATE essays SET flagged = ? WHERE id = ?', (new_flag, essay_id))
    db.commit()
    action = 'flagged' if new_flag else 'unflagged'
    log_action(session['username'], 'admin', action, 'essay', essay_id)
    flash(f'Essay has been {action}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/essay/<int:essay_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_essay_edit(essay_id):
    db = get_db()
    essay = db.execute('SELECT * FROM essays WHERE id = ?', (essay_id,)).fetchone()
    
    if essay is None:
        flash('Essay not found.', 'error')
        return redirect(url_for('admin_dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        country = request.form.get('country', '').strip()
        year_applied = request.form.get('year_applied', '').strip()
        interview_status = request.form.get('interview_status', '').strip()
        created_at = request.form.get('created_at', '').strip()
        
        # Reconstruct essays list from form
        essay_count = int(request.form.get('essay_count', 0))
        new_essays = []
        for i in range(essay_count):
            p = request.form.get(f'prompt_{i}', '').strip()
            r = request.form.get(f'response_{i}', '').strip()
            if r:
                new_essays.append({'prompt': p, 'response': r})
        
        errors = []
        if not name:
            errors.append('Name is required.')
        if not country:
            errors.append('Country is required.')
        if not year_applied or not year_applied.isdigit():
            errors.append('Year applied must be a valid year.')
        if interview_status not in ('yes', 'no', 'pending'):
            errors.append('Interview status must be valid.')
        if not created_at:
            errors.append('Submitted date is required.')
        if not new_essays:
            errors.append('At least one essay response is required.')
            
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin_edit_essay.html', essay=essay)
            
        db.execute('''
            UPDATE essays 
            SET name = ?, country = ?, year_applied = ?, interview_status = ?, created_at = ?, essays_json = ?
            WHERE id = ?
        ''', (name, country, int(year_applied), interview_status, created_at, json.dumps(new_essays), essay_id))
        db.commit()
        
        log_action(session['username'], 'admin', 'edited', 'essay', essay_id)
        flash('Essay details updated successfully.', 'success')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('admin_edit_essay.html', essay=essay)


@app.route('/admin/user/block', methods=['POST'])
@admin_required
def admin_block_user():
    email = request.form.get('email', '').strip() or None
    name = request.form.get('name', '').strip() or None
    reason = request.form.get('reason', '').strip()

    if not reason:
        flash('Reason is required for blocking.', 'error')
        return redirect(url_for('admin_dashboard'))
    if not email and not name:
        flash('Email or name is required.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    db.execute('INSERT INTO blocked_users (email, name, reason, blocked_by) VALUES (?, ?, ?, ?)',
               (email, name, reason, session['username']))
    db.commit()
    log_action(session['username'], 'admin', 'blocked', 'user', details=f"email={email}, name={name}", reason=reason)
    flash(f'User blocked: {name or email}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/unblock/<int:block_id>', methods=['POST'])
@admin_required
def admin_unblock_user(block_id):
    db = get_db()
    db.execute('DELETE FROM blocked_users WHERE id = ?', (block_id,))
    db.commit()
    log_action(session['username'], 'admin', 'unblocked', 'user', block_id)
    flash('User unblocked.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/maintenance/toggle', methods=['POST'])
@admin_required
def admin_toggle_maintenance():
    db = get_db()
    current = db.execute("SELECT value FROM site_settings WHERE key = 'maintenance_mode'").fetchone()
    new_val = 'false' if current and current['value'] == 'true' else 'true'
    db.execute("UPDATE site_settings SET value = ? WHERE key = 'maintenance_mode'", (new_val,))
    db.commit()
    status = 'enabled' if new_val == 'true' else 'disabled'
    log_action(session['username'], 'admin', f'maintenance_{status}', 'system')
    flash(f'Maintenance mode {status}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/moderator/<int:mod_id>/<action>', methods=['POST'])
@admin_required
def admin_mod_action(mod_id, action):
    if action not in ('accepted', 'rejected'):
        abort(400)
    db = get_db()
    db.execute('UPDATE moderator_applications SET status = ? WHERE id = ?', (action, mod_id))
    db.commit()
    log_action(session['username'], 'admin', action, 'mod_application', mod_id)
    flash(f'Moderator application has been {action}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/volunteer/create/<int:mod_id>', methods=['POST'])
@admin_required
def admin_create_volunteer(mod_id):
    db = get_db()
    app_data = db.execute('SELECT * FROM moderator_applications WHERE id = ? AND status = ?',
                          (mod_id, 'accepted')).fetchone()
    if app_data is None:
        flash('Application not found or not accepted.', 'error')
        return redirect(url_for('admin_dashboard'))

    # Generate credentials
    username = f"vol_{app_data['name'].lower().replace(' ', '_')}_{secrets.token_hex(3)}"
    access_key = secrets.token_urlsafe(16)

    db.execute('''
        INSERT INTO volunteers (username, access_key_hash, name, email, application_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (username, generate_password_hash(access_key), app_data['name'], app_data['email'], mod_id))
    db.commit()

    log_action(session['username'], 'admin', 'created_volunteer', 'volunteer', mod_id,
               details=f"username={username}")

    flash(f'Volunteer account created! Username: {username} | Access Key: {access_key} - Send these credentials to {app_data["email"]} securely.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/volunteer/deactivate/<int:vol_id>', methods=['POST'])
@admin_required
def admin_deactivate_volunteer(vol_id):
    db = get_db()
    db.execute('UPDATE volunteers SET active = 0 WHERE id = ?', (vol_id,))
    db.commit()
    log_action(session['username'], 'admin', 'deactivated', 'volunteer', vol_id)
    flash('Volunteer deactivated.', 'success')
    return redirect(url_for('admin_dashboard') + '#volunteers-tab')


# File serving (admin only)
@app.route('/admin/uploads/<filename>')
@admin_required
def admin_view_upload(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name)


@app.route('/admin/documents/<filename>')
@admin_required
def admin_view_document(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(app.config['DOCUMENTS_FOLDER'], safe_name)


@app.route('/admin/volunteer-ids/<filename>')
@admin_required
def admin_view_volunteer_id(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(app.config['VOLUNTEER_IDS_FOLDER'], safe_name)


# ---------------------------------------------------------------------------
# Volunteer Routes
# ---------------------------------------------------------------------------

@app.route('/volunteer/login', methods=['GET', 'POST'])
def volunteer_login():
    if session.get('role') == 'volunteer':
        return redirect(url_for('volunteer_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        access_key = request.form.get('access_key', '')

        db = get_db()
        vol = db.execute('SELECT * FROM volunteers WHERE username = ? AND active = 1',
                         (username,)).fetchone()

        if vol and check_password_hash(vol['access_key_hash'], access_key):
            session.clear()
            session['role'] = 'volunteer'
            session['username'] = username
            session['volunteer_id'] = vol['id']
            return redirect(url_for('volunteer_dashboard'))
        else:
            flash('Invalid username or access key.', 'error')

    return render_template('volunteer_login.html')


@app.route('/volunteer/dashboard')
@volunteer_required
def volunteer_dashboard():
    db = get_db()
    pending_essays = db.execute(
        'SELECT * FROM essays WHERE status = ? ORDER BY created_at DESC', ('pending',)
    ).fetchall()
    return render_template('volunteer_dashboard.html', pending_essays=pending_essays)


@app.route('/volunteer/essay/<int:essay_id>/<action>', methods=['POST'])
@volunteer_required
def volunteer_essay_action(essay_id, action):
    if action not in ('approved', 'rejected'):
        abort(400)

    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('You must provide a reason for your decision.', 'error')
        return redirect(url_for('volunteer_dashboard'))

    db = get_db()
    db.execute('UPDATE essays SET status = ?, moderated_by = ? WHERE id = ?',
               (action, session['username'], essay_id))
    db.commit()

    log_action(session['username'], 'volunteer', action, 'essay', essay_id, reason=reason)
    flash(f'Essay has been {action}. Reason recorded.', 'success')
    return redirect(url_for('volunteer_dashboard'))


@app.route('/volunteer/uploads/<filename>')
@volunteer_required
def volunteer_view_upload(filename):
    safe_name = secure_filename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_name)


@app.route('/volunteer/logout')
def volunteer_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(413)
def file_too_large(e):
    flash('File is too large. Maximum upload size is 10 MB.', 'error')
    return redirect(url_for('submit'))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)
