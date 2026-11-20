# FinFlow — Personal Finance Tracker

FinFlow is a Flask application for recording personal income and expenses, monitoring budgets, and tracking savings goals. It uses a per-user SQLite database model so each account sees its own financial records.

## Features

- User registration, login, logout, and profile/password updates.
- Expense records with categories, notes, dates, and recurring flags.
- Rule-based expense category suggestions from descriptions.
- Income tracking by source.
- Monthly dashboard with income, expenses, net balance, trends, and category summaries.
- Category budgets and savings goals with deposits.
- CSV and PDF report exports.
- Admin overview and user management.
- Authenticated JSON endpoints for expense, income, and summary data.

## Technology

Python, Flask, Flask-SQLAlchemy, SQLite, Flask-Login, Matplotlib, WeasyPrint, Jinja templates, and Tailwind CSS (CDN).

## Project structure

```text
FinFlow/
├── app.py
├── instance/             # SQLite database is created here at runtime
├── templates/            # Jinja HTML templates
└── requirements.txt
```

## Run locally

Python 3.10+ is recommended.

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Install Python dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Set a private session signing key before starting the application.

Windows PowerShell:

```powershell
$env:SECRET_KEY = "replace-with-a-long-random-secret"
python app.py
```

macOS / Linux:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Open http://127.0.0.1:5000 in your browser. The SQLite database and tables are created automatically in `instance/expenses.db`.

The first registered account is assigned the administrator role. Register that account first in a fresh local database.

## PDF export dependency

WeasyPrint may require operating-system libraries in addition to the Python package. Follow the official WeasyPrint installation instructions for your operating system if PDF export cannot initialize.

## Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing key. Set a stable, private value for each deployment. |
| `SESSION_COOKIE_SECURE` | Set to `true` when serving over HTTPS. Defaults to `false` for local development. |
| `FLASK_DEBUG` | Set to `true` only for local debugging. Defaults to `false`. |

## Important limitations

- SQLite is suitable for local demonstration and light usage; a multi-user public deployment should use a managed database and an appropriate backup strategy.
- Expense categorization is keyword-based, not a trained AI model.
- Monthly spending projection is a simple average-based estimate.
- This is a portfolio project, not a regulated financial service.
- Before public deployment, add CSRF protection to all state-changing forms, rate-limit authentication routes, configure HTTPS, and review privacy, backup, and production database settings.

## License

No license file is currently included. Contact the repository owner before reusing or redistributing the code.
