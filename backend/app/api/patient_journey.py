from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import AlertLog, CareEpisode, CareTask, FollowupCallNote, FollowupReminderLog, Patient, WhatsAppEvent

router = APIRouter(prefix="/api/patient-journey", tags=["Patient Journey"], dependencies=[Depends(get_current_user)])

def iso(value):
    return value.isoformat() if value is not None else None

@router.get("/{patient_id}")
def get_patient_journey(patient_id: UUID, db: Session = Depends(get_db)):
    """Read-only chronological timeline of records explicitly linked to one patient ID."""
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    events = []
    def add(kind, category, title, description, occurred_at, status=None, details=None):
        events.append({"id": f"{kind}:{len(events)}", "kind": kind, "category": category,
                       "title": title, "description": description or "", "occurred_at": iso(occurred_at),
                       "status": status, "details": details or {}})
    add("patient_registered", "care", "Patient registered", f"Registration type: {patient.registration_flow.replace('_', ' ').title()}", patient.created_at, patient.status,
        {"patient_ref": patient.patient_ref, "department": patient.department, "source": patient.source})
    episodes = db.scalars(select(CareEpisode).where(CareEpisode.patient_id == patient_id).order_by(CareEpisode.created_at.desc())).all()
    episode_ids = [x.episode_id for x in episodes]
    episode_by_id = {x.episode_id: x for x in episodes}
    for ep in episodes:
        add("care_episode", "care", f"Care episode created · {ep.episode_ref}", ep.reason_for_care or "Care episode recorded", ep.created_at, ep.status,
            {"episode_ref": ep.episode_ref, "department": ep.department, "doctor": ep.treating_doctor,
             "admission_date": iso(ep.admission_date), "discharge_date": iso(ep.discharge_date),
             "care_start_date": iso(ep.care_start_date), "care_end_date": iso(ep.care_end_date)})
    tasks = db.scalars(select(CareTask).where(CareTask.episode_id.in_(episode_ids)).order_by(CareTask.created_at.desc())).all() if episode_ids else []
    task_by_id = {x.task_id: x for x in tasks}
    for task in tasks:
        ep = episode_by_id.get(task.episode_id)
        add("care_task", "care", f"Care task created · {task.title}", task.instructions or task.task_type.replace("_", " ").title(), task.created_at, task.status,
            {"task_type": task.task_type, "episode_ref": ep.episode_ref if ep else None, "start_date": iso(task.start_date),
             "end_date": iso(task.end_date), "selected_slots": task.selected_slots or []})
    notes = db.scalars(select(FollowupCallNote).where(FollowupCallNote.patient_id == patient_id).order_by(FollowupCallNote.called_at.desc())).all()
    for note in notes:
        add("followup_call", "followups", f"Follow-up call · {note.call_outcome.replace('_', ' ').title()}", note.notes, note.called_at, note.status,
            {"call_outcome": note.call_outcome, "next_followup_date": iso(note.next_followup_date), "confirmed_surgery_date": iso(note.confirmed_surgery_date)})
    messages = db.scalars(select(WhatsAppEvent).where(WhatsAppEvent.patient_id == patient_id).order_by(WhatsAppEvent.received_at.desc())).all()
    for msg in messages:
        details = {"direction": msg.direction, "attention_flag": msg.attention_flag, "attention_note": msg.attention_note}
        if msg.episode_id in episode_by_id:
            details["episode_ref"] = episode_by_id[msg.episode_id].episode_ref
        add("whatsapp", "whatsapp", f"WhatsApp · {msg.direction.title()}", msg.message_text, msg.received_at, msg.status, details)
        if msg.attention_flag:
            add("whatsapp_attention", "whatsapp", "WhatsApp message flagged for follow-up", msg.attention_note or "Staff marked this message for follow-up.", msg.attention_updated_at or msg.received_at, "OPEN")
    alerts = db.scalars(select(AlertLog).where(AlertLog.patient_id == patient_id).order_by(AlertLog.created_at.desc())).all()
    for alert in alerts:
        task = task_by_id.get(alert.task_id)
        add("alert_preview", "alerts", f"Care reminder preview · {task.title if task else 'Care task'}", alert.message_preview, alert.created_at, alert.status,
            {"channel": alert.channel, "scheduled_date": iso(alert.scheduled_date), "slot": alert.slot})
    reminders = db.scalars(select(FollowupReminderLog).where(FollowupReminderLog.patient_id == patient_id).order_by(FollowupReminderLog.created_at.desc())).all()
    for reminder in reminders:
        add("followup_reminder", "alerts", f"Follow-up reminder preview · {reminder.reminder_type.replace('_', ' ').title()}", reminder.message_preview, reminder.created_at, reminder.status,
            {"channel": reminder.channel, "appointment_date": iso(reminder.appointment_date), "reminder_date": iso(reminder.reminder_date)})
    events.sort(key=lambda x: x["occurred_at"] or "", reverse=True)
    return {"patient": {"patient_id": str(patient.patient_id), "patient_ref": patient.patient_ref, "full_name": patient.full_name,
                         "registration_flow": patient.registration_flow}, "total_events": len(events), "events": events}
