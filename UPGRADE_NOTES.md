# Care Plus update: follow-up workflow and dashboard

This update adds:
- Doctor dropdown for post-discharge care episodes.
- Source dropdown for OPD and surgery follow-up registrations.
- Surgery call note history and status tracking.
- OPD attendance status and department/doctor filters.
- Date-range dashboard KPIs with department and doctor filters.

## Existing local database

On application startup, the backend runs `Base.metadata.create_all` and additive PostgreSQL changes for `patients.source`, `patients.followup_status`, and `care_episodes.doctor_id`. The new `followup_call_notes` table is created automatically.

Back up the database before upgrading. This automatic schema update is intended for local MVP development; use versioned Alembic migrations before production.

## KPI definitions
- New patients: patients created within the selected date range.
- OPD planned/attended/pending: OPD follow-ups whose visit date falls in the range; attendance is updated in the OPD Follow-ups page.
- Surgery planned/confirmed/refused: surgery follow-ups whose surgery date falls in the range, classified by current follow-up status.
- Active post-discharge episodes: active care episodes overlapping the selected date range.

Call notes are internal records; this update does not initiate telephone calls or send messages.
