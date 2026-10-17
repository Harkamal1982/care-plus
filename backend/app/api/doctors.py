from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import Doctor

router = APIRouter(prefix="/api/doctors", tags=["Doctors"], dependencies=[Depends(get_current_user)])

class DoctorCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    department: str = Field(min_length=2, max_length=80)

class DoctorUpdate(BaseModel):
    is_active: bool

def serialize(d: Doctor):
    return {"doctor_id": str(d.doctor_id), "full_name": d.full_name, "department": d.department, "is_active": d.is_active}

@router.get("")
def list_doctors(department: str | None = Query(default=None, max_length=80), include_inactive: bool = False, db: Session = Depends(get_db)):
    query = select(Doctor).order_by(Doctor.department, Doctor.full_name)
    if not include_inactive:
        query = query.where(Doctor.is_active.is_(True))
    if department:
        query = query.where(Doctor.department == department)
    return [serialize(d) for d in db.scalars(query).all()]

@router.post("", status_code=201)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db)):
    doctor = Doctor(full_name=payload.full_name.strip(), department=payload.department, is_active=True)
    db.add(doctor)
    try:
        db.commit(); db.refresh(doctor)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A doctor with this name already exists in this department.") from exc
    return serialize(doctor)

@router.patch("/{doctor_id}")
def update_doctor(doctor_id: UUID, payload: DoctorUpdate, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor: raise HTTPException(status_code=404, detail="Doctor not found")
    doctor.is_active = payload.is_active
    db.commit(); db.refresh(doctor)
    return serialize(doctor)
