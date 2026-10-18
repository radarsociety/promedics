# Promedics

An admin website for patient records and hospital visit histories. Uses Python 3.12+ and SQLite, with no third-party dependencies. The interface uses Calibri at a base size of 12pt (with system font fallbacks where Calibri is unavailable).

## Start

From `/workspace/promedics`:

```bash
python3 server.py --create-admin admin
python3 server.py --host 127.0.0.1 --port 8000
```

The first command asks for a password of at least 12 characters. Run it only to create an account; existing usernames are not overwritten. On this prepared machine, an initial admin already exists; its generated credentials are in the ignored `data/initial-admin.txt` file.

Open port 8000 in a browser using your hosting platform's supported preview or forwarded port. This cloud onboarding interface does not provide public preview URLs. For local use, run the commands on your own machine and open its port 8000 in a browser.

## Features

- Admin sign-in and sign-out, password hashing, eight-hour sessions, login throttling, and CSRF protection.
- Add and edit patients, including full name, date of birth, optional phone and notes.
- Automatically assigned seven-character codes containing both letters and numbers. Codes stay unchanged when editing a patient.
- Click a patient’s profile icon to see age (calculated from date of birth), gender, allergies, blood type, disabilities, height in cm and weight in kg. These details are editable; blank allergy and disability fields mean not recorded, rather than confirmed absent. Existing databases upgrade automatically without losing records.
- Search by name or code, including partial matches and case-insensitive searches.
- Record visit dates, reasons, medicines and optional notes; see the newest visits first.
- Dashboard counts and responsive layouts.

## Data

Records are stored in `data/promedics.sqlite3`, excluded from Git. Set `PROMEDICS_DB` to use a different database path. Back up the database with SQLite's backup API while the server is running, or copy it while the server is stopped. Live sessions are memory-only and administrators sign in again after a restart.

## Checks

```bash
python3 -m unittest discover -s tests -v
node --check static/app.js
```

The integration test uses a temporary database and fictional records. It checks access controls, patient creation and updates, searches, visit history, date validation, persistence and logout.

## Hosting

To make a public preview, deploy the application on a host with Python and persistent storage, run `python3 server.py --host 0.0.0.0 --port 8000`, and configure an HTTPS reverse proxy. Set `PROMEDICS_SECURE_COOKIE=1` behind HTTPS. Keep the database and credentials outside the web document root. The application serves only the explicitly listed static assets.

This is an initial implementation. Use fictional data for evaluation. Before handling real patient records, add the hospital's required access policies, audit trail, encrypted backups, account recovery, deployment hardening and operational review. There is currently one administrator role, and no patient self-service login.

## Render deployment

`render.yaml` configures a Docker web service with a persistent disk so patient records survive deployments. It uses Render's paid Starter plan and disk; review the cost in Render before creating resources. No hosting resources have been created from this workspace.

1. Publish these project files to your GitHub repository.
2. Sign in to Render, create a Blueprint, and select `radarsociety/promedics`.
3. Review the service and persistent disk, then deploy.
4. Render supplies the public HTTPS site address. In its environment settings, find the generated `PROMEDICS_ADMIN_PASSWORD`; the initial username is `admin`. Do not share this password publicly.

`deploy.py` creates an administrator only if the persistent database has no admin. Redeployments preserve existing accounts, patient records and patient codes. Changing the initial password environment variable does not reset an existing account.
