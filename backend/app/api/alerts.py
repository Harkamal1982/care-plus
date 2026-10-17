from datetime import date, time, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import AlertLog, CareEpisode, CareTask, FollowupReminderLog, Patient
from app.api.auth import get_current_user
router = APIRouter(prefix="/api/alerts", tags=["Alerts"], dependencies=[Depends(get_current_user)])
SLOT_LABELS = {"EARLY_MORNING": ("Early morning", "05:00–08:00"), "MORNING": ("Morning", "08:00–12:00"), "AFTERNOON": ("Afternoon", "12:00–16:00"), "EVENING": ("Evening", "16:00–20:00"), "NIGHT": ("Night", "20:00–23:00")}
@router.post("/preview-due")
def preview_due_alerts(db: Session = Depends(get_db), preview_date: date | None = None):
    """Log preview reminders for every active task/date/selected slot. Never sends messages."""
    target_date = preview_date or date.today()
    tasks = db.scalars(select(CareTask).where(CareTask.start_date <= target_date, CareTask.end_date >= target_date, CareTask.status == "SCHEDULED")).all()
    created=[]
    for task in tasks:
        episode=db.get(CareEpisode, task.episode_id); patient=db.get(Patient, episode.patient_id) if episode else None
        if not patient: continue
        for slot in task.selected_slots or []:
            if db.scalar(select(AlertLog.alert_id).where(AlertLog.task_id==task.task_id, AlertLog.scheduled_date==target_date, AlertLog.slot==slot)): continue
            label, hours=SLOT_LABELS.get(slot, (slot, "time to be confirmed"))
            message=f"Care Plus reminder for {patient.full_name}: {task.title}. Reminder window: {label} ({hours}). Follow your care team's instructions."
            db.add(AlertLog(task_id=task.task_id, patient_id=patient.patient_id, scheduled_date=target_date, slot=slot, channel="PREVIEW", status="PREVIEW_ONLY", message_preview=message))
            created.append({"patient_ref":patient.patient_ref,"task_id":str(task.task_id),"scheduled_date":str(target_date),"slot":slot,"message_preview":message,"note":"Preview only; no message was sent."})
    # OPD and surgery follow-up reminders are due one day before the appointment.
    appointment_date = target_date + timedelta(days=1)
    followup_patients = db.scalars(
        select(Patient).where(
            ((Patient.registration_flow == "OPD_FOLLOWUP") & (Patient.visit_date == appointment_date))
            | ((Patient.registration_flow == "SURGERY_FOLLOWUP") & (Patient.surgery_date == appointment_date))
        )
    ).all()
    for patient in followup_patients:
        reminder_type = patient.registration_flow
        exists = db.scalar(select(FollowupReminderLog.reminder_id).where(
            FollowupReminderLog.patient_id == patient.patient_id,
            FollowupReminderLog.reminder_type == reminder_type,
            FollowupReminderLog.appointment_date == appointment_date,
        ))
        if exists:
            continue
        label = "OPD follow-up" if reminder_type == "OPD_FOLLOWUP" else "surgery"
        message = f"Care Plus reminder for {patient.full_name}: your {label} is scheduled for {appointment_date}. Please contact the hospital if you need to change your appointment."
        db.add(FollowupReminderLog(
            patient_id=patient.patient_id,
            reminder_type=reminder_type,
            appointment_date=appointment_date,
            reminder_date=target_date,
            channel="PREVIEW",
            status="PREVIEW_ONLY",
            message_preview=message,
        ))
        created.append({
            "patient_ref": patient.patient_ref,
            "reminder_type": reminder_type,
            "appointment_date": str(appointment_date),
            "reminder_date": str(target_date),
            "message_preview": message,
            "note": "Preview only; no call or message was sent.",
        })
    db.commit()
    return {"preview_date":str(target_date),"created_count":len(created),"alerts":created,"note":"Preview logs only. No SMS, WhatsApp message, or call was sent."}
