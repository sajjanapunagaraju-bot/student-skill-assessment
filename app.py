import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super_secret_college_key_change_this'

# CONFIGURATION: Only allow this email domain
ALLOWED_DOMAIN = "@vvit.net"  # Change to your college domain (e.g., @college.edu)
DB_NAME = "assessment.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Users table (Role: 'student' or 'teacher')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                section TEXT NOT NULL
            )
        ''')
        # Exams table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                teacher_id INTEGER NOT NULL,
                section TEXT NOT NULL,
                end_time TEXT NOT NULL,
                FOREIGN KEY (teacher_id) REFERENCES users(id)
            )
        ''')
        # Questions table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_option TEXT NOT NULL,
                FOREIGN KEY (exam_id) REFERENCES exams(id)
            )
        ''')
        # Attempts / Results table (UNIQUE constraint ensures 1 attempt per student per exam)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(exam_id, student_id),
                FOREIGN KEY (exam_id) REFERENCES exams(id),
                FOREIGN KEY (student_id) REFERENCES users(id)
            )
        ''')

init_db()

# --- ROUTES ---

@app.route('/')
def home():
    if 'user_id' in session:
        if session['role'] == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        role = request.form['role']
        section = request.form['section'].strip().upper()

        # STRICT COLLEGE ID CHECK
        if not email.endswith(ALLOWED_DOMAIN):
            flash(f"Access Denied: Personal IDs are not allowed. Use your {ALLOWED_DOMAIN} ID.", "error")
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (name, email, password, role, section) VALUES (?, ?, ?, ?, ?)",
                    (name, email, hashed_pw, role, section)
                )
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("This College ID is already registered.", "error")

    return render_template('register.html', domain=ALLOWED_DOMAIN)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        # STRICT COLLEGE ID CHECK
        if not email.endswith(ALLOWED_DOMAIN):
            flash(f"Only official {ALLOWED_DOMAIN} IDs can log in.", "error")
            return redirect(url_for('login'))

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            session['section'] = user['section']
            return redirect(url_for('home'))
        else:
            flash("Invalid College ID or Password.", "error")

    return render_template('login.html', domain=ALLOWED_DOMAIN)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- TEACHER ROUTES ---

@app.route('/teacher', methods=['GET', 'POST'])
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))

    conn = get_db()
    teacher_id = session['user_id']
    teacher_section = session['section']

    # Handle creating a new exam
    if request.method == 'POST':
        title = request.form['title']
        end_time = request.form['end_time']  # Format: YYYY-MM-DDTHH:MM
        
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO exams (title, teacher_id, section, end_time) VALUES (?, ?, ?, ?)",
            (title, teacher_id, teacher_section, end_time)
        )
        exam_id = cursor.lastrowid

        # Save questions submitted dynamically
        q_texts = request.form.getlist('q_text[]')
        opt_as = request.form.getlist('opt_a[]')
        opt_bs = request.form.getlist('opt_b[]')
        opt_cs = request.form.getlist('opt_c[]')
        opt_ds = request.form.getlist('opt_d[]')
        corrects = request.form.getlist('correct[]')

        for i in range(len(q_texts)):
            if q_texts[i].strip():
                cursor.execute('''
                    INSERT INTO questions (exam_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (exam_id, q_texts[i], opt_as[i], opt_bs[i], opt_cs[i], opt_ds[i], corrects[i]))

        conn.commit()
        flash("Exam published successfully!", "success")
        return redirect(url_for('teacher_dashboard'))

    # Fetch exams created by THIS teacher
    exams = conn.execute("SELECT * FROM exams WHERE teacher_id = ? ORDER BY id DESC", (teacher_id,)).fetchall()
    
    # Fetch students ONLY in THIS teacher's section
    students = conn.execute("SELECT * FROM users WHERE role = 'student' AND section = ?", (teacher_section,)).fetchall()

    # Fetch submissions ONLY for THIS teacher's exams and section
    results = conn.execute('''
        SELECT u.name, u.email, e.title, e.end_time, s.score, s.total
        FROM submissions s
        JOIN users u ON s.student_id = u.id
        JOIN exams e ON s.exam_id = e.id
        WHERE e.teacher_id = ? AND u.section = ?
        ORDER BY e.id DESC, s.score DESC
    ''', (teacher_id, teacher_section)).fetchall()

    conn.close()
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return render_template('teacher_dashboard.html', exams=exams, students=students, results=results, now_str=now_str)

# --- STUDENT ROUTES ---

@app.route('/student')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    conn = get_db()
    student_id = session['user_id']
    student_section = session['section']
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

    # Get exams assigned to student's section
    exams = conn.execute("SELECT * FROM exams WHERE section = ? ORDER BY id DESC", (student_section,)).fetchall()
    
    # Get student's submissions
    subs = conn.execute("SELECT * FROM submissions WHERE student_id = ?", (student_id,)).fetchall()
    sub_map = {sub['exam_id']: sub for sub in subs}
    conn.close()

    exam_list = []
    for ex in exams:
        is_over = now_str >= ex['end_time']
        submission = sub_map.get(ex['id'])
        exam_list.append({
            'id': ex['id'],
            'title': ex['title'],
            'end_time': ex['end_time'].replace('T', ' '),
            'is_over': is_over,
            'attempted': submission is not None,
            'score': submission['score'] if submission else None,
            'total': submission['total'] if submission else None
        })

    return render_template('student_dashboard.html', exams=exam_list)

@app.route('/exam/<int:exam_id>', methods=['GET', 'POST'])
def take_exam(exam_id):
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    conn = get_db()
    student_id = session['user_id']
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

    exam = conn.execute("SELECT * FROM exams WHERE id = ? AND section = ?", (exam_id, session['section'])).fetchone()
    if not exam:
        conn.close()
        flash("Exam not found.", "error")
        return redirect(url_for('student_dashboard'))

    # 1. Check if already attempted (SINGLE ATTEMPT ENFORCEMENT)
    existing = conn.execute("SELECT * FROM submissions WHERE exam_id = ? AND student_id = ?", (exam_id, student_id)).fetchone()
    if existing:
        conn.close()
        flash("You have already completed this exam. Only 1 attempt is allowed.", "error")
        return redirect(url_for('student_dashboard'))

    # 2. Check if exam time is over
    if now_str >= exam['end_time']:
        conn.close()
        flash("Exam time has expired.", "error")
        return redirect(url_for('student_dashboard'))

    questions = conn.execute("SELECT * FROM questions WHERE exam_id = ?", (exam_id,)).fetchall()

    if request.method == 'POST':
        score = 0
        total = len(questions)
        for q in questions:
            selected = request.form.get(f"q_{q['id']}")
            if selected == q['correct_option']:
                score += 1

        try:
            conn.execute(
                "INSERT INTO submissions (exam_id, student_id, score, total, submitted_at) VALUES (?, ?, ?, ?, ?)",
                (exam_id, student_id, score, total, now_str)
            )
            conn.commit()
            flash("Exam submitted! Your score will appear once the exam window ends.", "success")
        except sqlite3.IntegrityError:
            flash("Duplicate submission blocked.", "error")
        
        conn.close()
        return redirect(url_for('student_dashboard'))

    conn.close()
    return render_template('take_exam.html', exam=exam, questions=questions)

if __name__ == '__main__':
    app.run(debug=True)
