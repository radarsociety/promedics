# Promedics — Sites edition

Adapted from radarsociety/promedics. This edition hosts the existing patient interface on ChatGPT Sites, using a persistent Cloudflare D1 database and ChatGPT authentication. No Render service is needed.

Features: patient registration, immutable unique seven-character alphanumeric codes, search by name/code, profile editing, visit history, latest visit reason, dashboard counts and a write audit trail. Profile fields include gender, DOB, height, weight, blood type, allergies, disabilities, eye colour, optional tribe, medical aid provider/number, address and emergency contact.

The Site is owner-private. APIs require authenticated identity and scope records to that identity. Mutations require same-origin JSON requests. Patient data is never stored in GitHub. The database starts empty; this edition does not import a previous Python SQLite database. The Python application remains available in the original repository.

Checks: `node --check public/app.js`, `node scripts/test-patients.mjs`, and the Sites build helper. The integration checks use an in-memory SQLite database and fictional data. Browser QA was unavailable in the authoring environment.

Use fictional records during evaluation. This initial release is not certified for clinical deployment. Hospital-specific staff roles, backup/restore procedures, retention policies, audit review, and operational approval still need to be established before real patient data is entered. The current directory returns up to 500 matching records; refine the search for larger datasets. There is no deletion UI or attachment upload.

Schema migrations live in `drizzle/`. Generate new migrations after schema changes; never modify applied migrations. Publish through the Sites workflow with the existing project ID in `.openai/hosting.json`.
