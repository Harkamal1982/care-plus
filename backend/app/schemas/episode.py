from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
DEPARTMENTS = ["Orthopaedics", "ENT", "Gynaecology", "General Medicine", "General Surgery", "Cardiology", "Neurology", "Paediatrics", "Urology", "Other"]
class EpisodeCreate(BaseModel):
    patient_id: UUID
    department: str = "Other"
    treating_doctor: str | None = Field(default=None, max_length=150)
    doctor_id: UUID | None = None
    admission_date: date | None = None
    discharge_date: date
    care_start_date: date
    care_end_date: date
    reason_for_care: str | None = None
    @model_validator(mode="after")
    def validate_dates(self):
        if self.care_end_date < self.care_start_date: raise ValueError("care_end_date must be on or after care_start_date")
        if self.department not in DEPARTMENTS: raise ValueError(f"department must be one of {DEPARTMENTS}")
        return self
class EpisodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    episode_id: UUID
    episode_ref: str
    patient_id: UUID
    department: str
    treating_doctor: str | None
    doctor_id: UUID | None
    admission_date: date | None
    discharge_date: date
    care_start_date: date
    care_end_date: date
    reason_for_care: str | None
    status: str
    created_at: datetime
