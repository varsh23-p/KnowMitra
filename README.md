# SkillSwap – Student Skill Exchange Platform

> A full-stack web application where college students teach skills they know and learn new ones from peers — **no money involved, just knowledge**.

---

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Test Suite](#test-suite)
- [Screenshots](#screenshots)

---

## Introduction

SkillSwap is a peer-to-peer skill exchange platform designed for college students. Instead of paying for tutors or courses, students connect directly — one student teaches Python, another teaches Guitar, and they simply swap. The platform handles matching, scheduling requests, messaging, and tracking progress through a modern web interface.

---

## Features

| Module | What it does |
|---|---|
| **Authentication** | Register, login, logout with Werkzeug password hashing, brute-force lockout after 5 failed attempts |
| **Student Profiles** | Full profile with photo upload (magic-number validation), college, branch, year, bio, experience level |
| **Skill Management** | Add/edit/delete teaching and learning skills, set proficiency level (Beginner / Intermediate / Expert), create new platform skills |
| **Smart Matching** | Two-direction algorithm: 100% for mutual matches, 50% for one-way. Category filter, name/college search, score filter |
| **Exchange Requests** | Full state machine: pending → accepted → completed (or cancelled/rejected). Skill selection, intro message, notifications on every state change |
| **Messaging** | AJAX chat with 4-second polling, read receipts, per-conversation unread badges, conversation sidebar search |
| **Reviews & Ratings** | 1–5 star ratings with written feedback, duplicate prevention, average rating calculation, breakdown bars |
| **Analytics Dashboard** | 5 live stat cards + 4 Chart.js charts: teaching skills, learning skills, monthly activity, learning progress |
| **Admin Panel** | Secure admin-only area: user management (search, filter, activate/deactivate), exchange monitoring, reported users, skill deletion, platform stats |

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.13, Flask 3.1.3 |
| **Database** | SQLite via Flask-SQLAlchemy 3.1.1 |
| **Authentication** | Flask-Login 0.6.3, Werkzeug 3.1.9 |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript (ES2020) |
| **Charts** | Chart.js 4.4.0 |
| **Icons** | Font Awesome 6.5.0 |
| **Fonts** | Google Fonts (Inter) |
| **Testing** | pytest 9.2.0 |

---

## Installation

### Prerequisites

- Python 3.10+ installed
- Git (optional)

### Steps

```bash
# 1. Clone or download the project
git clone https://github.com/your-username/skillswap.git
cd skillswap

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
# Windows PowerShell:
.\venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Load sample data (creates the database + 8 demo students + 20 skills)
python seed.py

# 6. Start the application
python run.py
```

Then open **http://localhost:5000** in your browser.

---

## Running the Application

```bash
# Development server (debug mode, auto-reload)
python run.py

# Run the complete test suite
python -m pytest tests/ -v

# Run a specific test module
python -m pytest tests/test_auth.py -v
python -m pytest tests/test_matching.py -v

# Re-seed the database (WARNING: drops and recreates all tables)
python seed.py
```

### Demo credentials

| Role | Email | Password |
|---|---|---|
| **Admin** | `admin@skillswap.com` | `admin123` |
| Student | `arjun@iitb.edu` | `pass123` |
| Student | `priya@nit.edu` | `pass123` |
| Student | `rohan@bits.edu` | `pass123` |
| Student | `sneha@vit.edu` | `pass123` |
| Student | `kavya@nit.edu` | `pass123` |
| Student | `aditya@iitd.edu` | `pass123` |
| Student | `meera@psg.edu` | `pass123` |
| Student | `vikram@manipal.edu` | `pass123` |

---

## Project Structure

```
SkillSwap/
│
├── run.py                      # Entry point — starts Flask dev server
├── config.py                   # Dev / Testing / Production configs
├── seed.py                     # Sample data loader (run once)
├── requirements.txt            # Python dependencies
├── skillswap.db                # SQLite database (auto-created)
│
├── app/
│   ├── __init__.py             # App factory, blueprints, extensions
│   ├── models.py               # All SQLAlchemy models
│   ├── main.py                 # Landing page + public routes
│   ├── errors.py               # Custom 400/403/404/500 error handlers
│   │
│   ├── auth/
│   │   └── routes.py           # Register, login, logout, brute-force protection
│   │
│   ├── profile/
│   │   └── routes.py           # View, edit, browse student profiles + photo upload
│   │
│   ├── skills/
│   │   └── routes.py           # Skill library, manage teaching/learning lists
│   │
│   ├── matching/
│   │   └── routes.py           # Smart matching route (uses matching_service)
│   │
│   ├── exchanges/
│   │   └── routes.py           # Full exchange request state machine
│   │
│   ├── messages/
│   │   └── routes.py           # Inbox, conversation, AJAX send, AJAX poll
│   │
│   ├── reviews/
│   │   └── routes.py           # Add review, view reviews list
│   │
│   ├── dashboard/
│   │   └── routes.py           # Dashboard + 4 analytics chart endpoints
│   │
│   ├── admin/
│   │   └── routes.py           # Admin panel (users, exchanges, reports, skills)
│   │
│   ├── services/
│   │   └── matching_service.py # Pure-Python matching algorithm (no Flask deps)
│   │
│   ├── static/
│   │   ├── css/main.css        # Complete design system (38 component sections)
│   │   ├── js/main.js          # 22 JS modules (sidebar, modals, AJAX, etc.)
│   │   ├── uploads/            # Uploaded profile photos (gitignored)
│   │   └── images/             # Static images
│   │
│   └── templates/
│       ├── base.html           # Authenticated layout (sidebar + topbar)
│       ├── base_public.html    # Public layout (landing, auth)
│       ├── index.html          # Landing page
│       ├── auth/               # login.html, register.html, logout_confirm.html
│       ├── profile/            # view.html, edit.html, browse.html
│       ├── skills/             # manage.html, index.html
│       ├── matching/           # matches.html
│       ├── exchanges/          # index.html, send.html
│       ├── messages/           # inbox.html, conversation.html
│       ├── reviews/            # add.html, list.html
│       ├── dashboard/          # home.html
│       ├── admin/              # index.html, users.html, exchanges.html,
│       │                       #   skills.html, reported.html
│       └── errors/             # 400.html, 403.html, 404.html, 500.html
│
└── tests/
    ├── test_auth.py            # 57 tests — registration, login, sessions
    ├── test_profile_skills.py  # 56 tests — profile CRUD, skill management
    ├── test_matching.py        # 35 tests — algorithm + HTTP routes
    ├── test_exchanges.py       # 48 tests — all 5 statuses + transitions
    ├── test_messages.py        # 52 tests — AJAX send/poll, access control
    ├── test_reviews_analytics.py # 46 tests — reviews + all 4 chart endpoints
    └── test_admin.py           # 60 tests — authorization + all admin features
```

---

## Database Schema

### Tables

| Table | Key columns | Notes |
|---|---|---|
| `users` | `id`, `email` (unique), `password_hash`, `full_name`, `college`, `branch`, `year`, `bio`, `profile_photo`, `experience`, `is_admin`, `is_active`, `is_reported` | Central user table |
| `skills` | `id`, `name` (unique), `category`, `description`, `icon` | Platform-wide skill library |
| `user_teaching_skills` | `user_id`, `skill_id`, `proficiency` | Many-to-many: users ↔ skills they teach |
| `user_learning_skills` | `user_id`, `skill_id` | Many-to-many: users ↔ skills they want to learn |
| `exchange_requests` | `id`, `sender_id`, `receiver_id`, `skill_requested_id`, `skill_offered_id`, `message`, `status` | Status: pending/accepted/rejected/cancelled/completed |
| `messages` | `id`, `sender_id`, `receiver_id`, `content`, `is_read`, `created_at` | Chat messages between connected users |
| `reviews` | `id`, `reviewer_id`, `reviewee_id`, `exchange_id`, `rating` (1–5), `feedback` | One review per user per exchange |
| `notifications` | `id`, `user_id`, `title`, `body`, `link`, `icon`, `is_read` | In-app notification feed |

### Relationships

```
User ──< user_teaching_skills >── Skill
User ──< user_learning_skills >── Skill
User ──< ExchangeRequest (as sender)
User ──< ExchangeRequest (as receiver)
ExchangeRequest ──< Message (indirectly, via user pair)
ExchangeRequest ──< Review
User ──< Review (as reviewer)
User ──< Review (as reviewee)
User ──< Notification
```

---

## Test Suite

Tests are executed with **pytest** against an in-memory SQLite database (isolated per test).

```
354 tests total — 354 passed, 0 failed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  test_auth.py              57 tests
  test_profile_skills.py    56 tests
  test_matching.py          35 tests
  test_exchanges.py         48 tests
  test_messages.py          52 tests
  test_reviews_analytics.py 46 tests
  test_admin.py             60 tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Run them:

```bash
python -m pytest tests/ -v          # verbose output
python -m pytest tests/ -q          # quiet (summary only)
python -m pytest tests/test_auth.py # single module
```

---

## Security

- Passwords hashed with Werkzeug (`pbkdf2:sha256` + per-user salt)
- Brute-force protection: 5 failed login attempts → 15-minute lockout
- Session cookies: `HttpOnly=True`, `SameSite=Lax`
- Open-redirect prevention on `?next=` login param
- File upload: extension whitelist + magic-number validation (rejects renamed executables)
- All admin routes double-protected (`@login_required` + `@admin_required`)
- Admin cannot self-deactivate; admin accounts immune to toggle/report
- Input validation on every form (server-side, not just HTML5 `required`)
- Parameterized ORM queries throughout (no raw SQL interpolation)
- Custom 400/403/404/500 error pages

---

## Screenshots

> Add screenshots here after running the application.

**Landing Page**
![Landing](docs/screenshots/landing.png)

**Student Dashboard**
![Dashboard](docs/screenshots/dashboard.png)

**Smart Matching**
![Matching](docs/screenshots/matching.png)

**Skill Management**
![Skills](docs/screenshots/skills.png)

**Exchange Requests**
![Exchanges](docs/screenshots/exchanges.png)

**Messaging**
![Messages](docs/screenshots/messages.png)

**Reviews**
![Reviews](docs/screenshots/reviews.png)

**Admin Panel**
![Admin](docs/screenshots/admin.png)

---

## License

This project was built as an academic portfolio project. Free to use and adapt for educational purposes.
