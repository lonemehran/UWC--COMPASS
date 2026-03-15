# 🧭 UWC Compass

A student-built platform where applicants who reached the **second round of UWC selection** can share their essays to help future candidates navigate the application process.

> **Not officially affiliated with [UWC International](https://www.uwc.org).**

---

## Features

- **Essay submissions** with verification — applicants upload a screenshot of their second-round notification email
- **Moderation system** — volunteer moderators review and approve essays before they go live
- **Admin dashboard** — manage pending essays, review screenshots, accept/reject moderator applications
- **Security hardened** — CSRF protection, parameterized SQL, file upload validation (MIME + extension), UUID filenames

## Tech Stack

| Layer     | Technology         |
|-----------|--------------------|
| Backend   | Python Flask       |
| Database  | SQLite             |
| Frontend  | HTML + CSS         |
| Security  | Flask-WTF (CSRF), Pillow (MIME validation) |

---

## Run Locally

### Prerequisites
- Python 3.10+

### Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/UWC-COMPASS.git
cd UWC-COMPASS

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Visit **http://localhost:5000** in your browser.

Access the admin dashboard at **http://localhost:5000/admin**



---

## Project Structure

```
UWC-COMPASS/
├── app.py                          # Flask backend (routes, DB, security)
├── requirements.txt                # Python dependencies
├── essays.db                       # SQLite database (auto-created)
├── .gitignore
├── uploads/
│   └── verification_images/        # Uploaded screenshots (admin-only access)
├── static/
│   └── style.css                   # Design system
└── templates/
    ├── base.html                   # Shared layout
    ├── index.html                  # Home page
    ├── submit.html                 # Essay submission form
    ├── essays.html                 # Approved essays listing
    ├── essay_detail.html           # Full essay reading view
    ├── volunteer.html              # Moderator application form
    ├── admin.html                  # Admin dashboard
    ├── login.html                  # Admin login
    └── 404.html                    # Error page
```

---

## Upload to GitHub

```bash
cd UWC-COMPASS

# Initialize git
git init
git add .
git commit -m "Initial commit: UWC Compass platform"

# Create a GitHub repo (via github.com), then:
git remote add origin https://github.com/YOUR_USERNAME/UWC-COMPASS.git
git branch -M main
git push -u origin main
```

---


---

## Security

| Protection | Implementation |
|------------|---------------|
| SQL Injection | Parameterized queries throughout |
| XSS | Jinja2 auto-escaping enabled |
| CSRF | Flask-WTF CSRFProtect on all forms |
| File Uploads | Extension whitelist + MIME validation + UUID filenames |
| Admin Auth | Werkzeug password hashing + session-based login |
| File Access | Uploaded screenshots served only to authenticated admins |

---

## License

This project is open source and available for educational use.

Built with care by students, for students. 🧭
