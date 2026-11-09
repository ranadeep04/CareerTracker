# CareerTrack - Smart Job Application & Career Management System

## Features
1. User registration and login (hashed passwords, session-based access).
2. User-specific job application CRUD, search and status filtering.
3. Dashboard analytics with Chart.js (monthly application activity and status pipeline).
4. In-app follow-up reminders (overdue and upcoming dates; no email/background notifications).
5. Interview preparation tracker linked to applications.
6. Rule-based job-description skill matching (not a trained AI model).

## Run on Windows (VS Code terminal)
1. Open this folder in VS Code.
2. Create a virtual environment:
   `py -m venv venv`
3. Activate it:
   `.env\Scripts\activate`
4. Install dependencies:
   `py -m pip install -r requirements.txt`
5. Start:
   `py app.py`
6. Open http://127.0.0.1:5000
7. Register a new account and log in.

## Important
- SQLite database is created automatically at `instance/careertrack.db`.
- If you already have a previous `instance/careertrack.db`, back it up before using this new version. This implementation creates its own tables but does not migrate old application records from the earlier no-login schema.
- Charts use Chart.js from a CDN, so the browser needs internet access to load the chart library.
- For local learning only: before public deployment, set a strong SECRET_KEY environment variable, turn debug mode off, add CSRF protection, validate external URLs, and use production hosting/database settings.


## Resume upload and automatic skill matching

1. Install dependencies: `py -m pip install -r requirements.txt`.
2. Run the app: `py app.py`.
3. Open **My Skills & Resume** and upload a text-based PDF or TXT resume. Review/edit the detected comma-separated skills and save.
4. Add or edit a job application and paste its full job description into the Job Description field.
5. Open **Skill Analyzer**, select that saved application, and click Analyze. The app displays matched skills, missing skills, and a percentage.

The analyzer uses a built-in keyword/alias list; it is not a trained AI/ATS model. Scanned PDFs are not OCR-processed. Existing `instance/careertrack.db` data is preserved; the new candidate profile table is created automatically when the app starts. Resume files are stored under `instance/uploads/` and are not publicly served.
