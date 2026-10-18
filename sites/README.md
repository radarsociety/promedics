# Promedics — Sites edition

Adapted from radarsociety/promedics. This edition hosts the existing patient interface on ChatGPT Sites, using a persistent Cloudflare D1 database and administrator username/password authentication. No Render service is needed.

Features: patient registration, immutable unique seven-character alphanumeric codes, search by name/code, profile editing, visit history, latest visit reason, dashboard counts and a write audit trail. Profile fields include gender, DOB, height, weight, blood type, allergies, disabilities, eye colour, optional tribe, medical aid provider/number, address and emergency contact.

The login page is publicly reachable. Patient APIs require a valid administrator session and use the hospital record namespace. Mutations require same-origin JSON requests. Patient data is never stored in GitHub. The database starts empty; this edition does not import a previous Python SQLite database. The Python application remains available in the original repository.

Checks: `node --check public/app.js`, `node scripts/test-patients.mjs`, and the Sites build helper. The integration checks use an in-memory SQLite database and fictional data. Browser QA was unavailable in the authoring environment.

Use fictional records during evaluation. This initial release is not certified for clinical deployment. Hospital-specific staff roles, backup/restore procedures, retention policies, audit review, and operational approval still need to be established before real patient data is entered. The current directory returns up to 500 matching records; refine the search for larger datasets. There is no deletion UI or attachment upload.

Schema migrations live in `drizzle/`. Generate new migrations after schema changes; never modify applied migrations. Publish through the Sites workflow with the existing project ID in `.openai/hosting.json`.

## Administrator login

The landing page has an Admin login button and a username/password form. Runtime credentials are configured as secret Sites environment values `PROMEDICS_ADMIN_USERNAME` and `PROMEDICS_ADMIN_PASSWORD`; they are not in the client or repository. Successful login issues an eight-hour opaque session cookie with HttpOnly, Secure and SameSite=Strict flags. Only its SHA-256 hash is stored in D1. Logout deletes the server session. Five failed attempts per client IP (with a shared fallback when unavailable) in fifteen minutes are rate limited. ChatGPT sign-in is not required. The hospital namespace is retained from the existing records when an administrator logs in, preserving access to previously saved patients and their visit histories. The owner Edit site control belongs to the hosting platform.

## Data durability

The hosted D1 database is separate from deployed JavaScript and static assets. Redeployments reuse project `appgprj_6ad4969a3d8481918da8553a183c2563` and binding `DB`; do not create a replacement Site or database during updates. No startup seed, table reset or destructive migration is used. Applied migrations are immutable. Future schema changes must append bounded, non-destructive migrations, preserving patient IDs, patient codes, visits and audit history. Code rollback does not restore database contents; database deletion and deliberate data deletion are separate operations. The integration check re-instantiates the API module with the existing database and verifies an original-namespace patient and visit remain accessible after fresh admin login.
