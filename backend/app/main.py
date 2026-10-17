
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.db import models  # noqa: F401
from app.db.database import Base, engine
from app.api import (
    alerts,
    auth,
    doctors,
    episodes,
    patients,
    tasks,
    followups,
    deletions,
    whatsapp,
    patient_journey,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local development only.
    # Production schema changes should be applied through migrations.
    if os.getenv("APP_ENV", "development").lower() != "production":
        Base.metadata.create_all(bind=engine)

        # Additive local-MVP schema updates for existing installations.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE patients "
                    "ADD COLUMN IF NOT EXISTS source VARCHAR(80)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE patients "
                    "ADD COLUMN IF NOT EXISTS followup_status "
                    "VARCHAR(40) NOT NULL DEFAULT 'PLANNED'"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE patients "
                    "ADD COLUMN IF NOT EXISTS confirmed_surgery_date DATE"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE followup_call_notes "
                    "ADD COLUMN IF NOT EXISTS call_outcome "
                    "VARCHAR(40) NOT NULL DEFAULT 'CONTACTED'"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE followup_call_notes "
                    "ADD COLUMN IF NOT EXISTS next_followup_date DATE"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE followup_call_notes "
                    "ADD COLUMN IF NOT EXISTS confirmed_surgery_date DATE"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE care_episodes "
                    "ADD COLUMN IF NOT EXISTS doctor_id UUID NULL "
                    "REFERENCES doctors(doctor_id)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE whatsapp_events "
                    "ADD COLUMN IF NOT EXISTS attention_flag "
                    "BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE whatsapp_events "
                    "ADD COLUMN IF NOT EXISTS attention_note TEXT NULL"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE whatsapp_events "
                    "ADD COLUMN IF NOT EXISTS attention_updated_at "
                    "TIMESTAMPTZ NULL"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE whatsapp_events "
                    "ADD COLUMN IF NOT EXISTS attention_updated_by UUID NULL "
                    "REFERENCES staff_users(user_id)"
                )
            )

    yield


app = FastAPI(
    title="Care Plus API",
    description="Post-discharge patient care MVP",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = [
    origin.strip()
    for origin in settings.frontend_origin.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(patients.router)
app.include_router(episodes.router)
app.include_router(tasks.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(doctors.router)
app.include_router(followups.router)
app.include_router(deletions.router)
app.include_router(whatsapp.router)
app.include_router(patient_journey.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
