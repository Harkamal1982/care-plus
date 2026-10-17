from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import Patient, CareEpisode, FollowupCallNote

router = APIRouter(prefix="/api", tags=["Follow-ups and dashboard"], dependencies=[Depends(get_current_user)])

SURGERY_STATUSES = {"PLANNED", "CALLED", "CONFIRMED_FOR_SURGERY", "REFUSED_FOR_SURGERY", "RESCHEDULE_REQUESTED", "NOT_REACHABLE", "COMPLETED"}
CALL_OUTCOMES = {"CONTACTED", "NOT_REACHABLE", "BUSY_CALLBACK", "WRONG_NUMBER", "LEFT_MESSAGE", "OTHER"}

class CallNoteCreate(BaseModel):
    status: str = Field(min_length=2, max_length=40)
    call_outcome: str = Field(default="CONTACTED", min_length=2, max_length=40)
    notes: str = Field(min_length=1, max_length=5000)
    next_followup_date: date | None = None
    confirmed_surgery_date: date | None = None

    @model_validator(mode="after")
    def validate_call(self):
        if self.status not in SURGERY_STATUSES:
            raise ValueError("Invalid surgery follow-up status")
        if self.call_outcome not in CALL_OUTCOMES:
            raise ValueError("Invalid call outcome")
        if self.status == "CONFIRMED_FOR_SURGERY" and self.confirmed_surgery_date is None:
            raise ValueError("Confirmed surgery date is required when status is Confirmed for surgery")
        return self

def serialize_note(n):
    return {
        "note_id": str(n.note_id), "patient_id": str(n.patient_id), "status": n.status,
        "call_outcome": n.call_outcome, "notes": n.notes, "called_at": n.called_at,
        "next_followup_date": n.next_followup_date, "confirmed_surgery_date": n.confirmed_surgery_date,
        "staff_user_id": str(n.staff_user_id) if n.staff_user_id else None,
    }

@router.get("/followups/notes/{patient_id}")
def list_call_notes(patient_id: UUID, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    if patient.registration_flow != "SURGERY_FOLLOWUP":
        raise HTTPException(422, "Call notes are supported for surgery follow-up patients")
    rows = db.scalars(select(FollowupCallNote).where(FollowupCallNote.patient_id == patient_id).order_by(FollowupCallNote.called_at.desc())).all()
    return [serialize_note(n) for n in rows]

@router.post("/followups/notes/{patient_id}", status_code=201)
def add_call_note(patient_id: UUID, payload: CallNoteCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    if patient.registration_flow != "SURGERY_FOLLOWUP":
        raise HTTPException(422, "Call notes are supported for surgery follow-up patients")
    if payload.status not in SURGERY_STATUSES:
        raise HTTPException(422, "Invalid surgery follow-up status")
    if payload.call_outcome not in CALL_OUTCOMES:
        raise HTTPException(422, "Invalid call outcome")
    if payload.status == "CONFIRMED_FOR_SURGERY" and payload.confirmed_surgery_date is None:
        raise HTTPException(422, "Please enter the confirmed surgery date")

    note = FollowupCallNote(
        patient_id=patient_id, staff_user_id=getattr(user, "user_id", None),
        status=payload.status, call_outcome=payload.call_outcome, notes=payload.notes.strip(),
        next_followup_date=payload.next_followup_date,
        confirmed_surgery_date=payload.confirmed_surgery_date,
    )
    patient.followup_status = payload.status
    if payload.status == "CONFIRMED_FOR_SURGERY":
        patient.confirmed_surgery_date = payload.confirmed_surgery_date
    db.add(note)
    db.commit()
    db.refresh(note)
    return serialize_note(note)

@router.patch("/followups/status/{patient_id}")
def update_followup_status(patient_id: UUID, status: str = Query(..., max_length=40), db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    allowed = SURGERY_STATUSES if patient.registration_flow == "SURGERY_FOLLOWUP" else {"PLANNED", "ATTENDED", "CANCELLED", "RESCHEDULED"}
    if status not in allowed:
        raise HTTPException(422, "Invalid status for this follow-up type")
    patient.followup_status = status
    db.commit()
    return {"patient_id": str(patient.patient_id), "followup_status": patient.followup_status}

@router.get("/dashboard/kpis")
def dashboard_kpis(start_date: date = Query(...), end_date: date = Query(...), department: str | None = None, doctor_id: UUID | None = None, db: Session = Depends(get_db)):
    if end_date < start_date:
        raise HTTPException(422, "end_date must be on or after start_date")
    def base(flow):
        q = select(Patient).where(Patient.registration_flow == flow)
        if department: q = q.where(Patient.department == department)
        if doctor_id: q = q.where(Patient.doctor_id == doctor_id)
        return q
    opd = base("OPD_FOLLOWUP").where(Patient.visit_date >= start_date, Patient.visit_date <= end_date)
    surg = base("SURGERY_FOLLOWUP").where(func.coalesce(Patient.confirmed_surgery_date, Patient.surgery_date) >= start_date, func.coalesce(Patient.confirmed_surgery_date, Patient.surgery_date) <= end_date)
    discharge = select(CareEpisode).where(CareEpisode.care_start_date <= end_date, CareEpisode.care_end_date >= start_date)
    if department: discharge = discharge.where(CareEpisode.department == department)
    if doctor_id: discharge = discharge.where(CareEpisode.doctor_id == doctor_id)
    planned_opd = db.scalar(select(func.count()).select_from(opd.subquery())) or 0
    attended_opd = db.scalar(select(func.count()).select_from(opd.where(Patient.followup_status == "ATTENDED").subquery())) or 0
    planned_surgery = db.scalar(select(func.count()).select_from(surg.subquery())) or 0
    confirmed_surgery = db.scalar(select(func.count()).select_from(surg.where(Patient.followup_status == "CONFIRMED_FOR_SURGERY").subquery())) or 0
    refused_surgery = db.scalar(select(func.count()).select_from(surg.where(Patient.followup_status == "REFUSED_FOR_SURGERY").subquery())) or 0
    active_episodes = db.scalar(select(func.count()).select_from(discharge.where(CareEpisode.status == "ACTIVE").subquery())) or 0
    all_patients = db.scalar(select(func.count()).select_from(Patient).where(Patient.created_at >= start_date, Patient.created_at < date.fromordinal(end_date.toordinal() + 1))) or 0
    return {"start_date": start_date, "end_date": end_date, "total_new_patients": all_patients, "opd_planned": planned_opd, "opd_attended": attended_opd, "opd_pending": max(planned_opd - attended_opd, 0), "surgery_planned": planned_surgery, "surgery_confirmed": confirmed_surgery, "surgery_refused": refused_surgery, "post_discharge_active_episodes": active_episodes}
