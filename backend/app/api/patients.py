from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Doctor, Patient
from app.schemas.patient import PatientCreate, PatientResponse
from app.api.auth import get_current_user

router = APIRouter(
    prefix="/api/patients",
    tags=["Patients"],
    dependencies=[Depends(get_current_user)],
)


def next_patient_ref(db: Session) -> str:
    # Simple local-MVP generator; replace with a DB sequence for concurrent production use.
    count = db.scalar(select(func.count()).select_from(Patient)) or 0
    return f"PAT-{count + 1:06d}"
@router.post("", response_model=PatientResponse, status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    if payload.registration_flow in ("OPD_FOLLOWUP", "SURGERY_FOLLOWUP"):
        doctor = db.get(Doctor, payload.doctor_id)
        if not doctor or not doctor.is_active:
            raise HTTPException(status_code=422, detail="Selected doctor does not exist or is inactive.")
        if doctor.department != payload.department:
            raise HTTPException(status_code=422, detail="Selected doctor does not belong to the selected department.")
    patient = Patient(patient_ref=next_patient_ref(db), **data)
    db.add(patient)
    try:
        db.commit(); db.refresh(patient)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not create patient; retry or check patient reference generation.") from exc
    return patient
@router.get("", response_model=list[PatientResponse])
def list_patients(search: str | None = Query(default=None, max_length=150), mobile_number: str | None = Query(default=None, max_length=20), db: Session = Depends(get_db)):
    query = select(Patient).order_by(Patient.created_at.desc())
    if mobile_number: query = query.where(Patient.mobile_number == mobile_number)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Patient.full_name.ilike(term), Patient.patient_ref.ilike(term), Patient.mobile_number.ilike(term)))
    return list(db.scalars(query).all())
@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if not patient: raise HTTPException(status_code=404, detail="Patient not found")
    return patient
