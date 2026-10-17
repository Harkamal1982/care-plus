from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import (
    Patient, CareEpisode, CareTask, FollowupCallNote, FollowupReminderLog,
    AlertLog, DeletionAuditLog
)

router = APIRouter(prefix="/api", tags=["Safe deletions"], dependencies=[Depends(get_current_user)])


class DeleteRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def audit(db: Session, user, entity_type: str, entity_id: str, label: str, reason: str):
    db.add(DeletionAuditLog(
        staff_user_id=getattr(user, "user_id", None),
        action="DELETE", entity_type=entity_type, entity_id=entity_id,
        entity_label=label, reason=reason.strip(),
        details={"integrity_checked": True},
    ))


def count_for(db, model, *conditions):
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


@router.delete("/patients/{patient_id}")
def delete_patient(patient_id: UUID, payload: DeleteRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found.")
    episodes = count_for(db, CareEpisode, CareEpisode.patient_id == patient_id)
    tasks = count_for(db, CareTask, CareTask.episode_id.in_(select(CareEpisode.episode_id).where(CareEpisode.patient_id == patient_id)))
    call_notes = count_for(db, FollowupCallNote, FollowupCallNote.patient_id == patient_id)
    reminders = count_for(db, FollowupReminderLog, FollowupReminderLog.patient_id == patient_id)
    alert_logs = count_for(db, AlertLog, AlertLog.patient_id == patient_id)
    blockers = []
    if episodes: blockers.append(f"{episodes} care episode(s)")
    if tasks: blockers.append(f"{tasks} care task(s)")
    if call_notes: blockers.append(f"{call_notes} surgery call-history record(s)")
    if reminders: blockers.append(f"{reminders} follow-up reminder log(s)")
    if alert_logs: blockers.append(f"{alert_logs} alert log(s)")
    if blockers:
        raise HTTPException(409, "Patient cannot be deleted because linked records exist: " + ", ".join(blockers) + ". Delete or resolve dependent records first.")
    audit(db, user, "PATIENT", str(patient.patient_id), f"{patient.patient_ref} — {patient.full_name}", payload.reason)
    db.delete(patient)
    db.commit()
    return {"deleted": True, "entity_type": "PATIENT", "entity_id": str(patient_id)}


@router.delete("/followups/{patient_id}")
def delete_followup(patient_id: UUID, payload: DeleteRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Follow-up record not found.")
    if patient.registration_flow not in ("OPD_FOLLOWUP", "SURGERY_FOLLOWUP"):
        raise HTTPException(422, "This patient is not an OPD or surgery follow-up record.")
    # A follow-up is stored on the patient row in this MVP. Before deleting it,
    # enforce the same referential-integrity rules as patient deletion so this
    # endpoint cannot bypass checks and cascade-delete episodes/tasks.
    episodes = count_for(db, CareEpisode, CareEpisode.patient_id == patient_id)
    tasks = count_for(
        db,
        CareTask,
        CareTask.episode_id.in_(select(CareEpisode.episode_id).where(CareEpisode.patient_id == patient_id)),
    )
    notes = count_for(db, FollowupCallNote, FollowupCallNote.patient_id == patient_id)
    reminders = count_for(db, FollowupReminderLog, FollowupReminderLog.patient_id == patient_id)
    alert_logs = count_for(db, AlertLog, AlertLog.patient_id == patient_id)
    blockers = []
    if episodes:
        blockers.append(f"{episodes} care episode(s)")
    if tasks:
        blockers.append(f"{tasks} care task(s)")
    if notes:
        blockers.append(f"{notes} surgery call-history record(s)")
    if reminders:
        blockers.append(f"{reminders} follow-up reminder log(s)")
    if alert_logs:
        blockers.append(f"{alert_logs} alert log(s)")
    if blockers:
        raise HTTPException(
            409,
            "Follow-up cannot be deleted because linked records exist: "
            + ", ".join(blockers)
            + ". Preserve linked history and resolve dependent records first.",
        )
    label = f"{patient.patient_ref} — {patient.full_name} ({patient.registration_flow})"
    audit(db, user, "FOLLOWUP", str(patient.patient_id), label, payload.reason)
    db.delete(patient)
    db.commit()
    return {"deleted": True, "entity_type": "FOLLOWUP", "entity_id": str(patient_id)}


@router.delete("/episodes/{episode_id}")
def delete_episode(episode_id: UUID, payload: DeleteRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    episode = db.get(CareEpisode, episode_id)
    if not episode:
        raise HTTPException(404, "Care episode not found.")
    tasks = count_for(db, CareTask, CareTask.episode_id == episode_id)
    if tasks:
        raise HTTPException(409, f"Care episode cannot be deleted because it has {tasks} care task(s). Delete those tasks first.")
    label = f"{episode.episode_ref} — patient {episode.patient_id}"
    audit(db, user, "CARE_EPISODE", str(episode.episode_id), label, payload.reason)
    db.delete(episode)
    db.commit()
    return {"deleted": True, "entity_type": "CARE_EPISODE", "entity_id": str(episode_id)}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: UUID, payload: DeleteRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    task = db.get(CareTask, task_id)
    if not task:
        raise HTTPException(404, "Care task not found.")
    alerts = count_for(db, AlertLog, AlertLog.task_id == task_id)
    if alerts:
        raise HTTPException(409, f"Care task cannot be deleted because it has {alerts} alert/reminder preview log(s). Preserve the alert history.")
    label = f"{task.title} ({task.task_type})"
    audit(db, user, "CARE_TASK", str(task.task_id), label, payload.reason)
    db.delete(task)
    db.commit()
    return {"deleted": True, "entity_type": "CARE_TASK", "entity_id": str(task_id)}
