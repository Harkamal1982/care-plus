from datetime import date, datetime, time
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
ALLOWED_TASK_TYPES = {"MEDICATION", "DIAGNOSTIC", "OPD", "NURSE_VISIT", "PHYSIOTHERAPY", "CHECK_IN", "OTHER"}
ALLOWED_SLOTS = {"EARLY_MORNING", "MORNING", "AFTERNOON", "EVENING", "NIGHT"}
class TaskCreate(BaseModel):
    episode_id: UUID
    task_type: str
    title: str = Field(min_length=1, max_length=200)
    instructions: str | None = None
    start_date: date
    end_date: date
    selected_slots: list[str] = Field(min_length=1)
    @model_validator(mode="after")
    def validate_schedule(self):
        if self.end_date < self.start_date: raise ValueError("end_date must be on or after start_date")
        if len(set(self.selected_slots)) != len(self.selected_slots): raise ValueError("selected_slots must not contain duplicates")
        invalid = set(self.selected_slots) - ALLOWED_SLOTS
        if invalid: raise ValueError(f"Invalid time slot(s): {sorted(invalid)}")
        return self
class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: UUID
    episode_id: UUID
    task_type: str
    title: str
    instructions: str | None
    scheduled_date: date | None
    scheduled_time: time | None
    repeat_daily: bool
    start_date: date
    end_date: date
    selected_slots: list[str]
    status: str
    created_at: datetime
