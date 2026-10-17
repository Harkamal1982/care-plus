"""Idempotent PostgreSQL schema migration for the Care Plus scheduling update.
Run from project root after setting backend/.env. Adds/backfills columns only; never drops tables or rows.
"""
from sqlalchemy import text
from app.db.database import Base, engine
from app.db import models  # noqa: F401

# Creates the new doctors table if it does not exist; existing tables/rows are preserved.
Base.metadata.create_all(bind=engine)

statements = [
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS registration_flow VARCHAR(30) NOT NULL DEFAULT 'DISCHARGE'",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS visit_date DATE",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS surgery_date DATE",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS department VARCHAR(80)",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS doctor_id UUID",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_patients_doctor_id_doctors') THEN ALTER TABLE patients ADD CONSTRAINT fk_patients_doctor_id_doctors FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id); END IF; END $$",
    "ALTER TABLE care_episodes ADD COLUMN IF NOT EXISTS department VARCHAR(80) NOT NULL DEFAULT 'Other'",
    "ALTER TABLE care_tasks ADD COLUMN IF NOT EXISTS start_date DATE",
    "ALTER TABLE care_tasks ADD COLUMN IF NOT EXISTS end_date DATE",
    "ALTER TABLE care_tasks ADD COLUMN IF NOT EXISTS selected_slots JSONB NOT NULL DEFAULT '[]'::jsonb",
    """UPDATE care_tasks SET start_date = COALESCE(start_date, scheduled_date, CURRENT_DATE), end_date = COALESCE(end_date, scheduled_date, CURRENT_DATE), selected_slots = CASE WHEN selected_slots IS NULL OR selected_slots = '[]'::jsonb THEN '[\"MORNING\"]'::jsonb ELSE selected_slots END WHERE start_date IS NULL OR end_date IS NULL OR selected_slots IS NULL OR selected_slots = '[]'::jsonb""",
    "ALTER TABLE care_tasks ALTER COLUMN start_date SET NOT NULL",
    "ALTER TABLE care_tasks ALTER COLUMN end_date SET NOT NULL",
    "ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS scheduled_date DATE",
    "ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS slot VARCHAR(30)",
    "UPDATE alert_logs a SET scheduled_date = COALESCE(a.scheduled_date, t.scheduled_date, t.start_date, CURRENT_DATE), slot = COALESCE(a.slot, 'LEGACY') FROM care_tasks t WHERE a.task_id = t.task_id AND (a.scheduled_date IS NULL OR a.slot IS NULL)",
    "UPDATE alert_logs SET scheduled_date = CURRENT_DATE WHERE scheduled_date IS NULL",
    "UPDATE alert_logs SET slot = 'LEGACY' WHERE slot IS NULL",
    "ALTER TABLE alert_logs ALTER COLUMN scheduled_date SET NOT NULL",
    "ALTER TABLE alert_logs ALTER COLUMN slot SET NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_task_date_slot ON alert_logs (task_id, scheduled_date, slot)",
]
with engine.begin() as conn:
    for sql in statements:
        conn.execute(text(sql))
    # Demo entries make the dropdown testable immediately. Replace these with actual hospital doctors.
    for sql in ["INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Orthopaedics', 'Orthopaedics', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Orthopaedics' AND department = 'Orthopaedics')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo ENT', 'ENT', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo ENT' AND department = 'ENT')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Gynaecology', 'Gynaecology', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Gynaecology' AND department = 'Gynaecology')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo General Medicine', 'General Medicine', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo General Medicine' AND department = 'General Medicine')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo General Surgery', 'General Surgery', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo General Surgery' AND department = 'General Surgery')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Cardiology', 'Cardiology', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Cardiology' AND department = 'Cardiology')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Neurology', 'Neurology', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Neurology' AND department = 'Neurology')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Paediatrics', 'Paediatrics', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Paediatrics' AND department = 'Paediatrics')", "INSERT INTO doctors (doctor_id, full_name, department, is_active) SELECT gen_random_uuid(), 'Dr. Demo Urology', 'Urology', TRUE WHERE NOT EXISTS (SELECT 1 FROM doctors WHERE full_name = 'Dr. Demo Urology' AND department = 'Urology')"]:
        conn.execute(text(sql))
print("Care Plus schema migration completed. Existing records were preserved. Demo doctor entries were added where missing.")
