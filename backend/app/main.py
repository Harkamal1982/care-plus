from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db import models  # noqa: F401
from app.db.database import Base, engine
from app.api import alerts, auth, doctors, episodes, patients, tasks, followups, deletions, whatsapp

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local development only; use Alembic migrations before production.
    Base.metadata.create_all(bind=engine)
    # Additive local-MVP schema updates for existing installations.
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS source VARCHAR(80)"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS followup_status VARCHAR(40) NOT NULL DEFAULT 'PLANNED'"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS confirmed_surgery_date DATE"))
        conn.execute(text("ALTER TABLE followup_call_notes ADD COLUMN IF NOT EXISTS call_outcome VARCHAR(40) NOT NULL DEFAULT 'CONTACTED'"))
        conn.execute(text("ALTER TABLE followup_call_notes ADD COLUMN IF NOT EXISTS next_followup_date DATE"))
        conn.execute(text("ALTER TABLE followup_call_notes ADD COLUMN IF NOT EXISTS confirmed_surgery_date DATE"))
        conn.execute(text("ALTER TABLE care_episodes ADD COLUMN IF NOT EXISTS doctor_id UUID NULL REFERENCES doctors(doctor_id)"))
    yield
app = FastAPI(title="Care Plus API", description="Post-discharge patient care MVP", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])
app.include_router(patients.router); app.include_router(episodes.router); app.include_router(tasks.router); app.include_router(alerts.router)
app.include_router(auth.router); app.include_router(doctors.router); app.include_router(followups.router); app.include_router(deletions.router); app.include_router(whatsapp.router)
@app.get("/health")
def health_check(): return {"status": "ok"}
