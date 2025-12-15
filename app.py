# app.py - corrected and cleaned version
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
import re


################################
app = Flask(__name__)
app.secret_key = "your_secret_key_here"

# ---------------- File upload configuration ----------------
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Keep uploads inside your project folder (absolute paths)
DB_PATH = "jobportal.db"
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "resumes")
PROFILE_FOLDER = os.path.join(os.getcwd(), "uploads", "profiles")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROFILE_FOLDER"] = PROFILE_FOLDER

# ---------------- Database Helpers ----------------
def get_conn():
    """
    Always use this helper. It sets row_factory so rows behave like dicts
    (you can write row['column_name'] in templates and code).
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema if DB doesn't exist."""
    if not os.path.exists(DB_PATH):
        print("🔧 Creating database...")
        with sqlite3.connect(DB_PATH) as conn:
            with open("schema.sql", "r") as f:
                conn.executescript(f.read())
        print("✅ Database initialized!")


init_db()

# Set WAL mode for concurrency (optional but useful)
with get_conn() as conn:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.commit()

# ---------------- Utility ----------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------- Routes ----------------
@app.route('/')
def index():
    return render_template('index.html')


# -------- Register (Sign up) --------
# ...existing code...
@app.route('/signup', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', '')
        contact = request.form.get('contact', '').strip()

        raw_adhar = (request.form.get('adhar_no') or request.form.get('aadhar_number') or '').strip()
        adhar_clean = re.sub(r'\D', '', raw_adhar)

        if not all([name, email, password, role, contact]):
            flash("All fields are required.")
            return redirect(url_for('register'))

        if role == 'employer' and not adhar_clean:
            flash("Aadhar number is required for employers.")
            return redirect(url_for('register'))

        if adhar_clean and len(adhar_clean) != 12:
            flash("Aadhar number must be 12 digits.")
            return redirect(url_for('register'))

        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO users (name, email, password, role, adhar_no, contact) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, email, generate_password_hash(password), role, adhar_clean or None, contact)
                )
                conn.commit()

            if role == 'employer':
                flash('Registration successful! Your employer account will be reviewed soon.')
            else:
                flash('Registration successful! Please login.')
            return redirect(url_for('login'))

        except sqlite3.IntegrityError:
            flash("Email or Aadhar already registered.")
        except Exception as e:
            flash(f"Error during registration: {e}")

    return render_template('register.html')



# -------- Login --------
# ...existing code...
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Email and password required.')
            return redirect(url_for('login'))

        try:
            with get_conn() as conn:
                user = conn.execute(
                    "SELECT id, name, email, password, role, is_verified FROM users WHERE email=?",
                    (email,)
                ).fetchone()

            if not user:
                print(f"❌ Login failed: user {email} not found")
                flash('Invalid email or password.')
                return redirect(url_for('login'))

            if not check_password_hash(user['password'], password):
                print(f"❌ Login failed: wrong password for {email}")
                flash('Invalid email or password.')
                return redirect(url_for('login'))

            # Store session
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['email'] = user['email']
            session['role'] = user['role']
            session['is_verified'] = user['is_verified']

            print(f"✅ Login successful: {email} (role={user['role']}, verified={user['is_verified']})")

            # Route based on role
            if user['role'] == 'employer':
                return redirect(url_for('employer'))
            elif user['role'] == 'worker':
                return redirect(url_for('worker'))
            else:
                return redirect(url_for('index'))

        except Exception as e:
            print(f"❌ Login error: {e}")
            app.logger.exception("Login error")
            flash('Login error.')
            return redirect(url_for('login'))

    return render_template('login.html')
# ...existing code...


# -------- Logout --------
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('index'))


# -------- Worker Dashboard --------
@app.route("/worker")
def worker():
    if "user_id" not in session or session.get("role") != "worker":
        return redirect(url_for("login"))

    worker_id = session.get("user_id")

    # ----- FETCH JOBS -----
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT 
                category, id, title, description, salary, location, qualifications,
                workers_needed, duration, start_time, end_time
            FROM jobs
            ORDER BY category
        """).fetchall()

    jobs_by_category = {}
    for row in rows:
        cat = row['category'] or "Other"
        jobs_by_category.setdefault(cat, []).append({
            "id": row['id'],
            "title": row['title'],
            "description": row['description'],
            "salary": row['salary'],
            "location": row['location'],
            "qualifications": row['qualifications'],
            "workers_needed": row['workers_needed'],
            "duration": row['duration'],
            "start_time": row['start_time'],
            "end_time": row['end_time']
        })

    categories = sorted(jobs_by_category.keys())

    # ----- FETCH NOTIFICATIONS -----
    with get_conn() as conn:
        notifications = conn.execute("""
            SELECT 
                h.hired_at AS hired_at,
                j.title AS job_title,
                u.name AS employer_name,
                u.contact AS employer_contact
            FROM hired_workers h
            INNER JOIN jobs j ON h.job_id = j.id
            INNER JOIN users u ON h.employer_id = u.id
            WHERE h.worker_id = ?
            ORDER BY h.hired_at DESC
        """, (worker_id,)).fetchall()

    # ----- RENDER PAGE -----
    return render_template(
        "worker.html",
        name=session.get("name"),
        user_id=worker_id,
        jobs=jobs_by_category,
        categories=categories,
        notifications=notifications
    )



# -------- Worker Apply to Job --------
@app.route("/apply_job/<int:job_id>", methods=["POST"])
def apply_job(job_id):
    if "user_id" not in session or session.get("role") != "worker":
        return redirect(url_for("login"))

    worker_id = session["user_id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM applications WHERE worker_id=? AND job_id=?", (worker_id, job_id))
        if cur.fetchone():
            return jsonify({"message": "You already applied for this job!"}), 400
        cur.execute("INSERT INTO applications (worker_id, job_id) VALUES (?, ?)", (worker_id, job_id))
        conn.commit()
    return jsonify({"message": "Application submitted successfully!"})


# -------- Worker Profile (Resume) --------
@app.route('/worker_profile/<int:user_id>')
def worker_profile(user_id):
    with get_conn() as conn:
        profile = conn.execute("SELECT * FROM worker_profiles WHERE worker_id=?", (user_id,)).fetchone()

    if profile:
        return render_template('worker_profile.html', profile=profile)
    else:
        return redirect(url_for('edit_worker_profile', user_id=user_id))


# -------- Edit Worker Profile (with photo and resume) --------
@app.route('/edit_worker_profile', methods=['GET', 'POST'])
def edit_worker_profile():
    worker_id = session.get('user_id')
    if not worker_id:
        flash('Please log in to edit your profile.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        skills = request.form.get('skills')
        experience = request.form.get('experience')
        achievements = request.form.get('achievements')

        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['PROFILE_FOLDER'], filename)
                file.save(filepath)
                # store path relative to app root so templates can use url_for/send_from_directory
                photo_path = filename

        resume_path = None
        if 'resume' in request.files:
            rfile = request.files['resume']
            if rfile and rfile.filename:
                rname = secure_filename(rfile.filename)
                rpath = os.path.join(app.config['UPLOAD_FOLDER'], rname)
                rfile.save(rpath)
                resume_path = rname

        with get_conn() as conn:
            existing = conn.execute('SELECT * FROM worker_profiles WHERE worker_id=?', (worker_id,)).fetchone()
            # Safely get existing profile_photo/resume if present
            existing_photo = None
            existing_resume = None
            if existing:
                try:
                    existing_photo = existing['profile_photo']
                except Exception:
                    existing_photo = None
                try:
                    existing_resume = existing['resume_path']
                except Exception:
                    existing_resume = None

            if existing:
                conn.execute('''
                    UPDATE worker_profiles
                    SET skills=?, experience=?, achievements=?, profile_photo=?, resume_path=?
                    WHERE worker_id=?
                ''', (
                    skills,
                    experience,
                    achievements,
                    photo_path or existing_photo,
                    resume_path or existing_resume,
                    worker_id
                ))
            else:
                conn.execute('''
                    INSERT INTO worker_profiles (worker_id, skills, experience, achievements, profile_photo, resume_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (worker_id, skills, experience, achievements, photo_path, resume_path))
            conn.commit()

        flash('Profile updated successfully!', 'success')
        return redirect(url_for('worker_profile', user_id=worker_id))

    # GET request: show existing profile (if any)
    with get_conn() as conn:
        profile = conn.execute('SELECT * FROM worker_profiles WHERE worker_id=?', (worker_id,)).fetchone()
    return render_template('edit_worker_profile.html', profile=profile)


# -------- Serve Uploaded Files --------
@app.route('/uploads/resumes/<filename>')
def uploaded_resume(filename):
    # Files saved in UPLOAD_FOLDER with filename only (not full path)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/uploads/profiles/<filename>')
def uploaded_profile(filename):
    return send_from_directory(app.config['PROFILE_FOLDER'], filename)


# -------- Employer Dashboard --------
@app.route('/employer')
def employer():
    if session.get('role') != 'employer':
        flash('Access denied.')
        return redirect(url_for('login'))

    user_id = session['user_id']

    # fetch verification status
    with get_conn() as conn:
        employer = conn.execute(
            "SELECT COALESCE(is_verified, 1) AS is_verified FROM users WHERE id=?",
            (user_id,)
        ).fetchone()

    if not employer:
        flash('User not found. Please log in again.')
        return redirect(url_for('login'))

    if employer['is_verified'] == 0:
        flash("⏳ Your account is pending admin verification.")
        return redirect(url_for('index'))

    # Fetch jobs for the left window
    with get_conn() as conn:
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE employer_id=? ORDER BY id DESC",
            (user_id,)
        ).fetchall()

    # Categories for right window Post Job form
    categories = [
        "House Help", "Construction", "Delivery", "Driver",
        "Shop & Market Work", "Other"
    ]

    return render_template(
        'employer.html',
        name=session.get("name"),
        jobs=jobs,
        categories=categories
    )



@app.route('/post-job', methods=['POST'])
def post_job():
    if 'user_id' not in session or session.get('role') != 'employer':
        flash("Please log in as an employer.")
        return redirect(url_for('login'))

    title = request.form['title']
    description = request.form['description']
    salary = request.form['salary']
    location = request.form['location']
    qualifications = request.form['qualifications']
    category = request.form['category']

    workers_needed = request.form['workers_needed']
    duration = request.form['duration']
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    employer_id = session['user_id']

    with get_conn() as db:
        db.execute('''INSERT INTO jobs 
            (employer_id, title, description, salary, location, qualifications, category,
             workers_needed, duration, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (employer_id, title, description, salary, location,
             qualifications, category, workers_needed, duration,
             start_time, end_time))
        db.commit()

    flash("Job posted successfully!")
    return redirect(url_for('employer'))




# -------- Manage Jobs --------
@app.route('/manage_jobs')
def manage_jobs():
    if 'user_id' not in session or session.get('role') != 'employer':
        return redirect(url_for('login'))
    with get_conn() as db:
        jobs = db.execute('SELECT * FROM jobs WHERE employer_id=?', (session['user_id'],)).fetchall()
    return render_template('manage_jobs.html', jobs=jobs)



# -------- Edit Job --------
@app.route('/edit_job/<int:job_id>', methods=['GET', 'POST'])
def edit_job(job_id):
    if 'user_id' not in session or session.get('role') != 'employer':
        return redirect(url_for('login'))

    with get_conn() as db:
        job = db.execute('SELECT * FROM jobs WHERE id = ? AND employer_id = ?', (job_id, session['user_id'])).fetchone()

    if not job:
        flash("You are not authorized to edit this job.")
        return redirect(url_for('manage_jobs'))

    if request.method == 'POST':
        data = (
            request.form['title'],
            request.form['description'],
            request.form['salary'],
            request.form['location'],
            request.form['qualifications'],
            request.form['category'],
            job_id, session['user_id']
        )
        with get_conn() as db:
            db.execute('''UPDATE jobs
                          SET title=?, description=?, salary=?, location=?, qualifications=?, category=?
                          WHERE id=? AND employer_id=?''', data)
            db.commit()
        flash("✅ Job updated successfully!")
        return redirect(url_for('manage_jobs'))

    categories = ["IT Jobs", "Construction", "Delivery", "Teaching", "Healthcare", "Other"]
    return render_template('edit_job.html', job=job, categories=categories)


# -------- Delete Job --------
@app.route('/delete_job/<int:job_id>', methods=['POST'])
def delete_job(job_id):
    if 'user_id' not in session or session.get('role') != 'employer':
        return redirect(url_for('login'))

    with get_conn() as db:
        db.execute('DELETE FROM jobs WHERE id = ? AND employer_id = ?', (job_id, session['user_id']))
        db.commit()
    flash("Job deleted successfully!")
    return redirect(url_for('manage_jobs'))


# -------- View Workers (for Employers) --------
@app.route('/view_workers')
def view_workers():
    if 'user_id' not in session or session.get('role') != 'employer':
        return redirect(url_for('login'))

    query = request.args.get('query', '').strip()

    with get_conn() as conn:
        if query:
            rows = conn.execute("""
                SELECT u.name, w.skills, w.experience, w.achievements, w.contact, w.resume_path, w.profile_photo
                FROM worker_profiles w
                JOIN users u ON w.worker_id = u.id
                WHERE u.name LIKE ? OR w.skills LIKE ?
            """, (f'%{query}%', f'%{query}%')).fetchall()
        else:
            rows = conn.execute("""
                SELECT u.name, w.skills, w.experience, w.achievements, w.contact, w.resume_path, w.profile_photo
                FROM worker_profiles w
                JOIN users u ON w.worker_id = u.id
            """).fetchall()

    # convert sqlite3.Row -> dict for template convenience (optional)
    workers = [dict(r) for r in rows]
    return render_template('view_workers.html', workers=workers)


# -------- View Applicants (for Employer) --------
@app.route('/view-applicants')
def view_applicants():
    employer_id = session.get('user_id')

    with get_conn() as conn:
        applicants = conn.execute("""
            SELECT 
                a.job_id,
                a.worker_id,
                j.title AS job_title,
                u.name AS worker_name,
                u.contact AS worker_contact,
                wp.skills,
                wp.experience,
                a.applied_at

            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            JOIN users u ON a.worker_id = u.id
            LEFT JOIN worker_profiles wp ON a.worker_id = wp.worker_id
            WHERE j.employer_id = ?
            ORDER BY a.applied_at DESC
        """, (employer_id,)).fetchall()

    return render_template('view_applicants.html', applicants=applicants)


# -------- Admin Login --------
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Hardcode one admin for simplicity
        if email == "admin@jobportal.com" and password == "1234":
            session['admin'] = True
            flash("Welcome, Admin!")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid admin credentials")

    return render_template('admin_login.html')


# -------- Admin Dashboard --------
@app.route('/admin')
def admin_dashboard():
    if not session.get('admin'):
        flash("Access denied.")
        return redirect(url_for('admin_login'))

    with get_conn() as conn:
        # select adhar_no and alias is_verified -> verified for template convenience
        employers = conn.execute("""
            SELECT id, name, email, adhar_no, is_verified AS verified
            FROM users
            WHERE role='employer'
        """).fetchall()

    return render_template('admin_dashboard.html', employers=employers)


# Verify employer (POST)
@app.route('/verify_employer/<int:employer_id>', methods=['POST'])
def verify_employer(employer_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    with get_conn() as conn:
        conn.execute("UPDATE users SET is_verified=1 WHERE id=?", (employer_id,))
        conn.commit()
    flash("✅ Employer verified successfully.")
    return redirect(url_for('admin_dashboard'))


# Reject (delete) employer (POST)
@app.route('/reject_employer/<int:employer_id>', methods=['POST'])
def reject_employer(employer_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (employer_id,))
        conn.commit()
    flash("❌ Employer rejected and removed.")
    return redirect(url_for('admin_dashboard'))


@app.route('/hire-worker', methods=['POST'])
def hire_worker():
    if 'user_id' not in session or session.get('role') != 'employer':
        flash("Unauthorized action.")
        return redirect(url_for('login'))

    employer_id = session['user_id']
    job_id = request.form['job_id']
    worker_id = request.form['worker_id']

    with get_conn() as conn:
        # Check if already hired
        exists = conn.execute("""
            SELECT id FROM hired_workers 
            WHERE job_id = ? AND worker_id = ?
        """, (job_id, worker_id)).fetchone()

        if exists:
            flash("You already hired this worker for the job.")
            return redirect(url_for('view_applicants'))

        # Insert hire record
        conn.execute("""
            INSERT INTO hired_workers (job_id, worker_id, employer_id)
            VALUES (?, ?, ?)
        """, (job_id, worker_id, employer_id))

        conn.commit()

    flash("Worker hired successfully!")
    return redirect(url_for('view_applicants'))


@app.route('/notifications')
def notifications():
    if 'user_id' not in session or session.get('role') != 'worker':
        return redirect(url_for('login'))

    worker_id = session['user_id']

    with get_conn() as conn:
        notifications = conn.execute("""
            SELECT 
                h.hired_at AS hired_at,
                j.title AS job_title,
                u.name AS employer_name,
                u.contact AS employer_contact
            FROM hired_workers h
            INNER JOIN jobs j ON h.job_id = j.id
            INNER JOIN users u ON h.employer_id = u.id
            WHERE h.worker_id = ?
            ORDER BY h.hired_at DESC
        """, (worker_id,)).fetchall()

    return render_template("worker_notifications.html", notifications=notifications)




# -------- Run Server --------
if __name__ == '__main__':
    app.run(debug=True)
