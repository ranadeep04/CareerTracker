import os
import re
import sqlite3
import uuid
from werkzeug.utils import secure_filename
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)
DATABASE = os.path.join(INSTANCE_DIR, "careertrack.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-local-development-key")
UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
ALLOWED_RESUME_EXTENSIONS = {"pdf", "txt"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        company TEXT NOT NULL,
        role TEXT NOT NULL,
        location TEXT DEFAULT '',
        job_link TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Applied',
        applied_date TEXT NOT NULL,
        follow_up_date TEXT DEFAULT '',
        follow_up_note TEXT DEFAULT '',
        job_description TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS candidate_profiles (
        user_id INTEGER PRIMARY KEY,
        skills TEXT DEFAULT '',
        resume_filename TEXT DEFAULT '',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        application_id INTEGER NOT NULL,
        interview_date TEXT DEFAULT '',
        round_name TEXT NOT NULL,
        questions TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        preparation_status TEXT DEFAULT 'Not Started',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
    );
    """)
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Enter all details. Password must contain at least 6 characters.", "danger")
            return render_template("register.html")
        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password))
            )
            db.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    db = get_db()
    user_id = session["user_id"]
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()

    query = "SELECT * FROM applications WHERE user_id = ?"
    params = [user_id]
    if search:
        query += " AND (company LIKE ? OR role LIKE ? OR location LIKE ?)"
        params.extend([f"%{search}%"] * 3)
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    query += " ORDER BY applied_date DESC, id DESC"
    applications = db.execute(query, params).fetchall()

    all_apps = db.execute(
        "SELECT * FROM applications WHERE user_id = ?", (user_id,)
    ).fetchall()
    total = len(all_apps)
    statuses = ["Applied", "Assessment", "Interview", "Offer", "Rejected"]
    status_counts = {
        status: sum(1 for app_row in all_apps if app_row["status"] == status)
        for status in statuses
    }
    today = date.today().isoformat()
    overdue = db.execute("""
        SELECT * FROM applications
        WHERE user_id = ? AND follow_up_date <> '' AND follow_up_date < ?
        ORDER BY follow_up_date
    """, (user_id, today)).fetchall()
    upcoming = db.execute("""
        SELECT * FROM applications
        WHERE user_id = ? AND follow_up_date >= ?
        ORDER BY follow_up_date LIMIT 5
    """, (user_id, today)).fetchall()

    month_counts = {}
    for row in all_apps:
        month = (row["applied_date"] or "")[:7]
        if month:
            month_counts[month] = month_counts.get(month, 0) + 1
    months = sorted(month_counts)[-6:]

    return render_template(
        "index.html", applications=applications, statuses=statuses,
        total=total, status_counts=status_counts, overdue=overdue,
        upcoming=upcoming, chart_labels=months,
        chart_values=[month_counts[m] for m in months],
        chart_status_values=[status_counts[s] for s in statuses],
        search=search, status_filter=status_filter, today=today
    )


@app.route("/add", methods=["POST"])
@login_required
def add_application():
    fields = {
        "company": request.form.get("company", "").strip(),
        "role": request.form.get("role", "").strip(),
        "location": request.form.get("location", "").strip(),
        "job_link": request.form.get("job_link", "").strip(),
        "status": request.form.get("status", "Applied"),
        "applied_date": request.form.get("applied_date", ""),
        "follow_up_date": request.form.get("follow_up_date", ""),
        "follow_up_note": request.form.get("follow_up_note", "").strip(),
        "job_description": request.form.get("job_description", "").strip(),
        "notes": request.form.get("notes", "").strip()
    }
    if not fields["company"] or not fields["role"] or not fields["applied_date"]:
        flash("Company, role and applied date are required.", "danger")
    else:
        get_db().execute("""
            INSERT INTO applications
            (user_id, company, role, location, job_link, status, applied_date,
             follow_up_date, follow_up_note, job_description, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session["user_id"], *fields.values()))
        get_db().commit()
        flash("Application added successfully.", "success")
    return redirect(url_for("index"))


@app.route("/edit/<int:app_id>", methods=["GET", "POST"])
@login_required
def edit_application(app_id):
    db = get_db()
    application = db.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (app_id, session["user_id"])
    ).fetchone()
    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        fields = [
            request.form.get("company", "").strip(),
            request.form.get("role", "").strip(),
            request.form.get("location", "").strip(),
            request.form.get("job_link", "").strip(),
            request.form.get("status", "Applied"),
            request.form.get("applied_date", ""),
            request.form.get("follow_up_date", ""),
            request.form.get("follow_up_note", "").strip(),
            request.form.get("job_description", "").strip(),
            request.form.get("notes", "").strip()
        ]
        if not fields[0] or not fields[1] or not fields[5]:
            flash("Company, role and applied date are required.", "danger")
        else:
            db.execute("""
                UPDATE applications SET company=?, role=?, location=?, job_link=?,
                status=?, applied_date=?, follow_up_date=?, follow_up_note=?,
                job_description=?, notes=? WHERE id=? AND user_id=?
            """, (*fields, app_id, session["user_id"]))
            db.commit()
            flash("Application updated.", "success")
            return redirect(url_for("index"))
    return render_template("edit.html", application=application)


@app.route("/delete/<int:app_id>", methods=["POST"])
@login_required
def delete_application(app_id):
    db = get_db()
    db.execute("DELETE FROM applications WHERE id = ? AND user_id = ?",
               (app_id, session["user_id"]))
    db.commit()
    flash("Application deleted.", "success")
    return redirect(url_for("index"))


SKILL_ALIASES = {
    "python": ["python"], "java": ["java"], "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"], "html": ["html", "html5"], "css": ["css", "css3"],
    "react": ["react", "react.js", "reactjs"], "angular": ["angular"], "vue": ["vue", "vue.js"],
    "flask": ["flask"], "django": ["django"], "fastapi": ["fastapi"], "sql": ["sql"],
    "mysql": ["mysql"], "postgresql": ["postgresql", "postgres"], "sqlite": ["sqlite"],
    "mongodb": ["mongodb", "mongo db"], "git": ["git"], "github": ["github"],
    "rest api": ["rest api", "restful api", "rest apis"], "machine learning": ["machine learning", "ml"],
    "deep learning": ["deep learning", "dl"], "pandas": ["pandas"], "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn"], "tensorflow": ["tensorflow"], "pytorch": ["pytorch"],
    "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"], "aws": ["aws", "amazon web services"],
    "azure": ["azure", "microsoft azure"], "communication": ["communication", "verbal communication"],
    "problem solving": ["problem solving", "problem-solving"], "data structures": ["data structures", "data structure", "ds"],
    "algorithms": ["algorithms", "algorithm"], "oops": ["oops", "object oriented programming", "object-oriented programming"],
    "linux": ["linux"], "c": ["c programming", "programming in c"], "c++": ["c++", "cpp"],
    "c#": ["c#", "c sharp"], "node.js": ["node.js", "nodejs"], "express.js": ["express.js", "expressjs"],
    "bootstrap": ["bootstrap"], "tailwind css": ["tailwind css", "tailwind"], "php": ["php"],
    "redis": ["redis"], "power bi": ["power bi", "powerbi"], "excel": ["excel", "microsoft excel"],
    "tableau": ["tableau"], "jenkins": ["jenkins"], " ci/cd": ["ci/cd", "continuous integration", "continuous deployment"],
    "agile": ["agile"], "scrum": ["scrum"], "selenium": ["selenium"], "pytest": ["pytest"],
    "unit testing": ["unit testing", "unit test"], "api testing": ["api testing"],
}


def extract_skills(text):
    content = (text or "").lower()
    found = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            pattern = r"(?<![a-z0-9])" + re.escape(alias.strip()) + r"(?![a-z0-9])"
            if re.search(pattern, content):
                found.append(canonical.strip())
                break
    return sorted(set(found))


def allowed_resume(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_RESUME_EXTENSIONS


def read_resume_text(file_storage):
    extension = file_storage.filename.rsplit(".", 1)[1].lower()
    if extension == "txt":
        return file_storage.read().decode("utf-8", errors="ignore")
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(file_storage.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@app.route("/skills", methods=["GET", "POST"])
@login_required
def skills_profile():
    db = get_db()
    user_id = session["user_id"]
    profile = db.execute("SELECT * FROM candidate_profiles WHERE user_id=?", (user_id,)).fetchone()
    if request.method == "POST":
        uploaded = request.files.get("resume")
        current_skills = request.form.get("skills", "").strip()
        resume_filename = profile["resume_filename"] if profile else ""
        if uploaded and uploaded.filename:
            if not allowed_resume(uploaded.filename):
                flash("Upload a PDF or TXT resume only.", "danger")
                return redirect(url_for("skills_profile"))
            try:
                resume_text = read_resume_text(uploaded)
                detected = extract_skills(resume_text)
                if not resume_text.strip():
                    flash("No readable text found. This may be a scanned PDF; enter skills manually.", "warning")
                else:
                    current_skills = ", ".join(detected)
                    safe_name = secure_filename(uploaded.filename) or "resume"
                    stored_name = f"{user_id}_{uuid.uuid4().hex}_{safe_name}"
                    uploaded.stream.seek(0)
                    uploaded.save(os.path.join(UPLOAD_DIR, stored_name))
                    resume_filename = uploaded.filename
                    flash(f"Resume analyzed. Detected {len(detected)} skills. Review and edit the list before saving.", "success")
            except Exception as exc:
                flash(f"Could not read this resume: {exc}", "danger")
                return redirect(url_for("skills_profile"))
        normalized = extract_skills(current_skills)
        # Preserve manually entered terms that are not in the built-in vocabulary.
        if current_skills:
            extras = [part.strip().lower() for part in current_skills.split(",") if part.strip() and part.strip().lower() not in normalized]
            normalized = sorted(set(normalized + extras))
        db.execute("""INSERT INTO candidate_profiles (user_id, skills, resume_filename, updated_at)
                      VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                      ON CONFLICT(user_id) DO UPDATE SET skills=excluded.skills,
                      resume_filename=excluded.resume_filename, updated_at=CURRENT_TIMESTAMP""",
                   (user_id, ", ".join(normalized), resume_filename))
        db.commit()
        flash("Your candidate skill profile has been saved.", "success")
        return redirect(url_for("skills_profile"))
    return render_template("skills.html", profile=profile)


@app.route("/analyzer", methods=["GET", "POST"])
@login_required
def analyzer():
    db = get_db()
    user_id = session["user_id"]
    applications = db.execute("SELECT id, company, role, job_description FROM applications WHERE user_id=? ORDER BY company, role", (user_id,)).fetchall()
    profile = db.execute("SELECT skills FROM candidate_profiles WHERE user_id=?", (user_id,)).fetchone()
    candidate_skills = [x.strip() for x in (profile["skills"] if profile else "").split(",") if x.strip()]
    result = None
    selected_id = request.values.get("application_id", type=int)
    if request.method == "POST":
        selected_id = request.form.get("application_id", type=int)
        application = db.execute("SELECT * FROM applications WHERE id=? AND user_id=?", (selected_id, user_id)).fetchone()
        if not application:
            flash("Please select one of your saved applications.", "danger")
        elif not application["job_description"].strip():
            flash("This application has no job description. Edit the application and add its job description first.", "warning")
        else:
            required = extract_skills(application["job_description"])
            matched = sorted(set(x.lower() for x in candidate_skills) & set(required))
            missing = sorted(set(required) - set(matched))
            score = round(len(matched) / len(required) * 100) if required else 0
            result = {"matched": matched, "missing": missing, "score": score,
                      "required": required, "company": application["company"], "role": application["role"]}
    selected = next((a for a in applications if a["id"] == selected_id), None)
    return render_template("analyzer.html", result=result, applications=applications,
                           selected_id=selected_id, selected=selected, candidate_skills=candidate_skills)


@app.route("/interviews")
@login_required
def interviews():
    rows = get_db().execute("""
        SELECT i.*, a.company, a.role
        FROM interviews i
        JOIN applications a ON a.id = i.application_id
        WHERE i.user_id = ? AND a.user_id = ?
        ORDER BY i.interview_date
    """, (session["user_id"], session["user_id"])).fetchall()
    applications = get_db().execute(
        "SELECT id, company, role FROM applications WHERE user_id = ? ORDER BY company",
        (session["user_id"],)
    ).fetchall()
    return render_template("interviews.html", interviews=rows, applications=applications)


@app.route("/interviews/add", methods=["POST"])
@login_required
def add_interview():
    application_id = request.form.get("application_id", type=int)
    owned = get_db().execute(
        "SELECT id FROM applications WHERE id=? AND user_id=?",
        (application_id, session["user_id"])
    ).fetchone()
    if not owned:
        flash("Select one of your own applications.", "danger")
        return redirect(url_for("interviews"))
    get_db().execute("""
        INSERT INTO interviews
        (user_id, application_id, interview_date, round_name, questions, notes, preparation_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        session["user_id"], application_id,
        request.form.get("interview_date", ""),
        request.form.get("round_name", "").strip(),
        request.form.get("questions", "").strip(),
        request.form.get("notes", "").strip(),
        request.form.get("preparation_status", "Not Started")
    ))
    get_db().commit()
    flash("Interview preparation entry added.", "success")
    return redirect(url_for("interviews"))


@app.route("/interviews/edit/<int:interview_id>", methods=["GET", "POST"])
@login_required
def edit_interview(interview_id):
    db = get_db()
    item = db.execute("""
        SELECT i.*, a.company, a.role
        FROM interviews i
        JOIN applications a ON a.id = i.application_id
        WHERE i.id = ? AND i.user_id = ? AND a.user_id = ?
    """, (interview_id, session["user_id"], session["user_id"])).fetchone()

    if not item:
        flash("Interview plan not found.", "danger")
        return redirect(url_for("interviews"))

    applications = db.execute(
        "SELECT id, company, role FROM applications WHERE user_id = ? ORDER BY company",
        (session["user_id"],)
    ).fetchall()

    if request.method == "POST":
        application_id = request.form.get("application_id", type=int)
        owned = db.execute(
            "SELECT id FROM applications WHERE id = ? AND user_id = ?",
            (application_id, session["user_id"])
        ).fetchone()
        round_name = request.form.get("round_name", "").strip()

        if not owned or not round_name:
            flash("Choose one of your applications and enter a round name.", "danger")
        else:
            db.execute("""
                UPDATE interviews
                SET application_id = ?, interview_date = ?, round_name = ?,
                    questions = ?, notes = ?, preparation_status = ?
                WHERE id = ? AND user_id = ?
            """, (
                application_id,
                request.form.get("interview_date", ""),
                round_name,
                request.form.get("questions", "").strip(),
                request.form.get("notes", "").strip(),
                request.form.get("preparation_status", "Not Started"),
                interview_id,
                session["user_id"]
            ))
            db.commit()
            flash("Interview plan updated successfully.", "success")
            return redirect(url_for("interviews"))

    return render_template("edit_interview.html", item=item, applications=applications)


@app.route("/interviews/update/<int:interview_id>", methods=["POST"])
@login_required
def update_interview(interview_id):
    status = request.form.get("preparation_status", "Not Started")
    get_db().execute("""
        UPDATE interviews SET preparation_status=?
        WHERE id=? AND user_id=?
    """, (status, interview_id, session["user_id"]))
    get_db().commit()
    flash("Preparation status updated.", "success")
    return redirect(url_for("interviews"))


@app.route("/interviews/delete/<int:interview_id>", methods=["POST"])
@login_required
def delete_interview(interview_id):
    get_db().execute("DELETE FROM interviews WHERE id=? AND user_id=?",
                     (interview_id, session["user_id"]))
    get_db().commit()
    flash("Interview entry deleted.", "success")
    return redirect(url_for("interviews"))


@app.context_processor
def inject_user():
    return {"current_user": session.get("user_name")}


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
