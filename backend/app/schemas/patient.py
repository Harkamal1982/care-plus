from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasPath, BaseModel, ConfigDict, Field, model_validator

RegistrationFlow = Literal["DISCHARGE", "OPD_FOLLOWUP", "SURGERY_FOLLOWUP"]
DEPARTMENTS = ["Orthopaedics", "ENT", "Gynaecology", "General Medicine", "General Surgery", "Cardiology", "Neurology", "Paediatrics", "Urology", "Other"]


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    mobile_number: str = Field(min_length=8, max_length=20)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = None
    registration_flow: RegistrationFlow = "DISCHARGE"
    visit_date: date | None = None
    surgery_date: date | None = None
    department: str | None = Field(default=None, max_length=80)
    doctor_id: UUID | None = None
    source: str | None = Field(default=None, max_length=80)
    followup_status: str = "PLANNED"

    @model_validator(mode="after")
    def validate_followup(self):
        if self.registration_flow == "OPD_FOLLOWUP" and self.visit_date is None:
            raise ValueError("visit_date is required for OPD follow-up")
        if self.registration_flow == "SURGERY_FOLLOWUP" and self.surgery_date is None:
            raise ValueError("surgery_date is required for surgery follow-up")
        if self.registration_flow != "OPD_FOLLOWUP" and self.visit_date is not None:
            raise ValueError("visit_date is only used for OPD follow-up")
        if self.registration_flow != "SURGERY_FOLLOWUP" and self.surgery_date is not None:
            raise ValueError("surgery_date is only used for surgery follow-up")
        if self.registration_flow in ("OPD_FOLLOWUP", "SURGERY_FOLLOWUP"):
            if not self.department:
                raise ValueError("department is required for OPD and surgery follow-up")
            if self.department not in DEPARTMENTS or self.department == "Other":
                raise ValueError(f"department must be one of {DEPARTMENTS[:-1]}")
            if self.doctor_id is None:
                raise ValueError("doctor_id is required for OPD and surgery follow-up")
        elif self.department is not None or self.doctor_id is not None:
            raise ValueError("department and doctor_id are only used for OPD/surgery follow-up")
        if self.source is not None and self.source not in ["Walk In", "Camp", "Reference", "Online", "Existing Patient", "Other"]:
            raise ValueError("source must be one of the configured source values")
        if self.registration_flow == "SURGERY_FOLLOWUP" and self.followup_status not in ["PLANNED", "CALLED", "CONFIRMED_FOR_SURGERY", "REFUSED_FOR_SURGERY", "RESCHEDULE_REQUESTED", "NOT_REACHABLE", "COMPLETED"]:
            raise ValueError("Invalid surgery follow-up status")
        return self


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    patient_id: UUID
    patient_ref: str
    full_name: str
    mobile_number: str
    date_of_birth: date | None
    gender: str | None
    email: str | None
    address: str | None
    registration_flow: RegistrationFlow
    visit_date: date | None
    surgery_date: date | None
    confirmed_surgery_date: date | None = None
    department: str | None
    doctor_id: UUID | None
    source: str | None = None
    followup_status: str
    doctor_name: str | None = Field(default=None, validation_alias=AliasPath("doctor", "full_name"))
    status: str
    created_at: datetime
