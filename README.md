# Care Plus MVP

Care Plus is a local-development staff portal for post-discharge patient care. Stack: React + Vite, FastAPI, SQLAlchemy, PostgreSQL. It includes staff login, patient registration, care episodes, care tasks, and preview-only reminder logs.

## Important safety and deployment notes
- Use fictitious test data until privacy/security, consent, audit trails, access controls, backups, and applicable healthcare compliance requirements have been reviewed.
- Reminder previews only write to `alert_logs`; no SMS or WhatsApp is sent and no background scheduler is installed.
- Fixed reminder windows are centrally defined in `backend/app/api/alerts.py`: Early morning 05:00–08:00, Morning 08:00–12:00, Afternoon 12:00–16:00, Evening 16:00–20:00, Night 20:00–23:00. Confirm these windows with the care team before operational use. Dates use the database/application host's local date; configure server timezone explicitly before deployment.
- Existing `hospital_name`, `scheduled_date`, and `scheduled_time` columns are retained for compatibility. Existing episodes get department `Other`; old tasks are backfilled to start/end on their former scheduled date and the Morning slot. Existing alert logs are preserved and tagged `LEGACY`.

## 1. Configure environment
Install Python 3.12+, Node.js/npm, and PostgreSQL. Ensure `careplus_db` and `careplus_user` exist. From the project root:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit backend/.env. Set DB_PASSWORD and a long random JWT_SECRET_KEY. Never commit .env.
```

Add this line to `backend/.env` (use a generated secret, not this placeholder):
```env
JWT_SECRET_KEY=replace_with_a_long_random_secret
```

## 2. Migrate existing data (do not drop the database)
Stop the backend first, then from the project root:

```bash
cd backend
source .venv/bin/activate
python migrate_existing_data.py
```

The migration adds columns and backfills existing records; it does not drop tables or rows. Take a PostgreSQL backup before running any migration. It is designed for PostgreSQL and is safe to rerun.

## 3. Start backend
From the project root, with the virtual environment active:

```bash
uvicorn app.main:app --app-dir backend --env-file backend/.env --reload
```

API docs: http://127.0.0.1:8000/docs · Health: http://127.0.0.1:8000/health

## 4. Create the first administrator
In a second terminal, from the project root:

```bash
cd backend
source .venv/bin/activate
python create_admin.py
```

Follow the prompts. Accounts are created by an administrator; staff login uses email and password. Admins can create staff accounts through `POST /api/auth/users` in the API docs with a bearer token.

## 5. Start frontend
In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, usually http://localhost:5173. Sign in with the administrator account.

## Features
- Separate Patient registration, Care episodes, and Care tasks pages.
- Single-hospital episode flow with a Department dropdown; legacy hospital names are retained in the database for data compatibility.
- Care task start/end dates and selected reminder slots. A preview is generated for each selected slot per day in the inclusive date range.
- Duplicate previews are prevented by a unique task/date/slot key. Re-running preview for the same date creates no duplicate logs.
- `POST /api/alerts/preview-due` accepts optional `preview_date=YYYY-MM-DD` and logs previews only; no messages are sent.

## API endpoints
- `GET /health`
- `POST /api/auth/login`, `GET /api/auth/me`, admin-only `POST /api/auth/users`
- `POST /api/patients`, `GET /api/patients`, `GET /api/patients/{patient_id}`
- `POST /api/episodes`, `GET /api/episodes?patient_id=<uuid>`
- `POST /api/tasks`, `GET /api/tasks?episode_id=<uuid>`
- `POST /api/alerts/preview-due`

## Migration caveats
The migration preserves legacy columns so existing data remains available. The old alert log schema may have existing duplicate task logs; if so, creating the new unique index can fail. In that case, inspect duplicates in `alert_logs` and reconcile them manually before rerunning; do not delete records without a reviewed backup. For production, move to versioned Alembic migrations and add audit logging, rate limiting, robust role/permission checks, automated backups, TLS, and a real scheduler/provider integration only after review.

## Patient-centred workflow update

The frontend now keeps one active patient context across the Care Episodes and Care Tasks pages:

1. Registering a patient automatically selects that patient and opens **Care episodes**.
2. Creating a care episode automatically selects that episode and opens **Care tasks**.
3. The first page lets staff search patients by name, patient reference, or mobile number and select the patient to continue an existing record.
4. A patient-context banner at the top of every page shows the active patient's reference, name, mobile number, and available basic demographics.
5. Episode and task lists are filtered to the active patient, and task episode choices are limited to that patient's episodes.

The changes are frontend-only and do not require a database migration. Keep your existing `.env` files and PostgreSQL database as they are.


## Patient registration pathways

Registration supports three pathways: `DISCHARGE` (the existing episode/task flow), `OPD_FOLLOWUP` (stores a visit date), and `SURGERY_FOLLOWUP` (stores a surgery date). OPD/surgery patients do not need a care episode or care task. The preview endpoint logs an appointment reminder for the day before the saved visit/surgery date. It does not send SMS, WhatsApp, or place calls; delivery requires a configured provider and a scheduled job.

### Apply the additive database migration

Back up the database first. From the backend directory with the project's virtual environment activated, run `python migrate_existing_data.py`. This adds the pathway/date columns without deleting existing data. Restart the backend after the migration.


## OPD and surgery follow-up doctor selection

The OPD Follow-up and Surgery Follow-up registration forms now require a department and doctor. The doctor dropdown is populated by the authenticated `GET /api/doctors?department=...` endpoint from the PostgreSQL `doctors` table. The backend checks that the chosen doctor is active and belongs to the selected department.

After extracting this project, from the project root run the existing Python environment and load `backend/.env` into the shell before running the migration:

```bash
cd ~/Projects/care-plus
source .venv/bin/activate
set -a
source backend/.env
set +a
PYTHONPATH=backend python backend/migrate_existing_data.py
```

The migration preserves existing patient and care data. It creates the `doctors` table, adds the new nullable patient columns, and inserts clearly labelled **demo doctors** only where matching demo rows are missing. Replace these demo entries with your hospital's actual doctors before using the workflow for real patients. For example, update a row in PostgreSQL with:

```sql
UPDATE doctors
SET full_name = 'Dr. Actual Name'
WHERE department = 'Orthopaedics'
  AND full_name = 'Dr. Demo Orthopaedics';
```

Restart the backend after the migration. Existing `.env` files and secrets are not included in the ZIP.


## Safe record deletion (local MVP)

This version adds DELETE endpoints for patients, OPD/surgery follow-up records, care episodes, and care tasks. Each permitted deletion requires a reason and writes a row to `deletion_audit_logs` with the authenticated staff user (when available), timestamp, entity, and reason.

Integrity safeguards:
- Patient deletion is blocked while care episodes/tasks, surgery call notes, follow-up reminder logs, or alert logs exist.
- OPD/surgery follow-up deletion is blocked when call-history or reminder-log records exist.
- Care episode deletion is blocked while care tasks exist.
- Care task deletion is blocked while alert/reminder preview logs exist.
- Delete requests are checked server-side; UI confirmation alone is not relied upon.

Before installing, back up PostgreSQL. Local development startup uses `Base.metadata.create_all()` to create the new audit table. For production, migrate schema with Alembic and use a formal retention policy rather than relying on startup DDL.

## WhatsApp Cloud API integration (optional)

The WhatsApp integration is disabled until credentials are configured. With no credentials, the existing Care Plus preview workflow remains preview-only and does not send messages.

### Environment variables

Add these values to `backend/.env` (do not commit this file):

```dotenv
WHATSAPP_ACCESS_TOKEN=your_meta_permanent_or_system_user_token
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_business_phone_number_id
WHATSAPP_APP_SECRET=your_meta_app_secret
WHATSAPP_VERIFY_TOKEN=choose_a_long_random_webhook_verification_token
WHATSAPP_API_VERSION=v23.0
```

Restart the backend after changing environment variables. `GET /api/whatsapp/status` (staff-authenticated) reports whether the required credentials are present. Never expose access tokens or the app secret in the frontend.

### Configure the Meta webhook

Set the callback URL to `https://YOUR_PUBLIC_API_HOST/api/whatsapp/webhook`, use the same `WHATSAPP_VERIFY_TOKEN`, and subscribe to the WhatsApp `messages` webhook field. The callback must be reachable over HTTPS. The endpoint validates `X-Hub-Signature-256` using `WHATSAPP_APP_SECRET`, ignores duplicate provider message IDs, stores inbound text and updates outbound delivery statuses when matching status events arrive.

### Endpoints

- `GET /api/whatsapp/status` — staff-authenticated configuration status.
- `POST /api/whatsapp/send` — staff-authenticated manual message send; JSON body: `{"patient_id":"...","episode_id":"...","message":"..."}`. The episode is optional but, if supplied, must belong to the patient.
- `GET /api/whatsapp/progress` — staff-authenticated message history; optional filters: `department`, `doctor_id`, `patient_id`.
- `GET /api/whatsapp/webhook` and `POST /api/whatsapp/webhook` — Meta webhook verification and signed event receiver.

The Patient WhatsApp progress screen displays the latest message events and a department filter. Incoming replies are automatically associated only if the sender's normalized last 10 digits match exactly one patient and that patient has exactly one active care episode. Otherwise the event is marked `NEEDS_REVIEW` and remains unassigned; do not guess the patient when phone numbers are shared. This MVP does not yet include a UI for manually resolving unmatched events.

### Important production limitations

- Free-form WhatsApp messages are generally permitted only during the customer-service window after the user messages the business. Outside that window, use an approved WhatsApp message template; this initial send endpoint intentionally does not bypass template rules.
- Obtain and record patient consent, provide a privacy notice and opt-out process, restrict access, define retention/deletion policies, and avoid sending sensitive clinical details in notifications.
- Host the webhook on a stable public HTTPS URL and configure Meta credentials before attempting real delivery. Local development alone cannot receive Meta webhooks.
- Before production, add formal database migrations, manual review/assignment of ambiguous replies, stronger phone normalization, monitoring/retries, and end-to-end tests with a Meta test number.
