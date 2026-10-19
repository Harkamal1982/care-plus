"""WhatsApp Cloud API integration.

Configure credentials in environment variables before enabling outbound delivery.
"""
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.services.whatsapp_media import (
    WhatsAppMediaError,
    create_presigned_image_url,
    store_whatsapp_image,
)
from app.db.models import (
    CareEpisode,
    Patient,
    User,
    WhatsAppEvent,
    WhatsAppMedia,
    WhatsAppNotification,
)

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


class SendMessage(BaseModel):
    patient_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


class AssignInboundMessage(BaseModel):
    patient_id: uuid.UUID
    episode_id: uuid.UUID | None = None


class AttentionUpdate(BaseModel):
    attention_flag: bool
    attention_note: str | None = Field(default=None, max_length=1000)


def normalize_indian_mobile(value: str) -> str:
    """Return an Indian mobile number as 91 + 10 digits.

    Accepted examples: 9878446888, +919878446888, 919878446888,
    and 09878446888.
    """
    digits = "".join(ch for ch in value if ch.isdigit())

    if len(digits) == 10:
        mobile = digits
    elif len(digits) == 12 and digits.startswith("91"):
        mobile = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        mobile = digits[1:]
    else:
        raise ValueError(
            "Expected a 10-digit Indian mobile number, optionally prefixed by 0 or 91."
        )

    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise ValueError("Invalid Indian mobile number.")

    return "91" + mobile


def sender_mobile_key(value: str) -> str | None:
    """Return the normalized 10-digit mobile, or None if unsupported."""
    try:
        return normalize_indian_mobile(value)[2:]
    except ValueError:
        return None


@router.get("/status", dependencies=[Depends(get_current_user)])
def status():
    configured = bool(
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        and os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        and os.getenv("WHATSAPP_APP_SECRET")
    )
    return {
        "configured": configured,
        "mode": "cloud_api" if configured else "preview_only",
        "note": (
            "Outbound free-form messages require an active WhatsApp "
            "customer-service window. Outside that window, use an approved template."
        ),
    }


@router.post("/send", dependencies=[Depends(get_current_user)])
async def send_message(payload: SendMessage, db: Session = Depends(get_db)):
    patient = db.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    episode = None
    if payload.episode_id:
        episode = db.get(CareEpisode, payload.episode_id)
        if not episode or episode.patient_id != patient.patient_id:
            raise HTTPException(
                400, "The selected episode does not belong to this patient"
            )

    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        raise HTTPException(
            503,
            "WhatsApp is not configured. Configure WHATSAPP_ACCESS_TOKEN "
            "and WHATSAPP_PHONE_NUMBER_ID.",
        )

    version = os.getenv("WHATSAPP_API_VERSION", "v26.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"

    try:
        to = normalize_indian_mobile(patient.mobile_number)
    except ValueError as exc:
        raise HTTPException(400, f"Patient mobile number is invalid: {exc}") from exc

    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": payload.message},
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://graph.facebook.com/{version}/{phone_id}/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.is_error:
            error = data.get("error", {})
            error_code = error.get("code")
            # Do not return provider internals or potentially sensitive details.
            detail = "WhatsApp API rejected the message"
            if error_code is not None:
                detail += f" (code {error_code})"
            raise HTTPException(response.status_code, detail)

    except httpx.HTTPError as exc:
        raise HTTPException(502, "WhatsApp API request failed") from exc

    messages = data.get("messages") or []
    wamid = messages[0].get("id") if messages else None
    if not wamid:
        raise HTTPException(
            502,
            "WhatsApp API returned no message ID; delivery could not be confirmed.",
        )

    event = WhatsAppEvent(
        patient_id=patient.patient_id,
        episode_id=episode.episode_id if episode else None,
        direction="OUTBOUND",
        phone_number=to,
        message_text=payload.message,
        provider_message_id=wamid,
        status="SENT",
        received_at=datetime.now(timezone.utc),
    )

    try:
        db.add(event)
        db.commit()
        db.refresh(event)
    except SQLAlchemyError as exc:
        db.rollback()
        # Meta may have accepted the message even though local persistence failed.
        # Do not retry sending automatically; the webhook may still reconcile it.
        raise HTTPException(
            502,
            "WhatsApp accepted or processed the request, but the message record "
            "could not be saved. Check message progress before retrying.",
        ) from exc

    return {
        "event_id": str(event.event_id),
        "status": "SENT",
        "provider_message_id": wamid,
        "recipient": to,
        "note": "SENT means accepted by WhatsApp; delivery is confirmed by a later callback.",
    }


@router.get("/progress", dependencies=[Depends(get_current_user)])
def progress(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        department: str | None = None,
        doctor_id: uuid.UUID | None = None,
        patient_id: uuid.UUID | None = None,
):
    # TODO before real patient data: enforce role/assignment-level access here.
    stmt = (
        select(WhatsAppEvent, Patient, CareEpisode)
        .outerjoin(Patient, Patient.patient_id == WhatsAppEvent.patient_id)
        .outerjoin(CareEpisode, CareEpisode.episode_id == WhatsAppEvent.episode_id)
        .where(WhatsAppEvent.episode_id.is_not(None))
        .order_by(WhatsAppEvent.received_at.desc())
        .limit(500)
    )

    rows = db.execute(stmt).all()
    result = []

    for event, patient, episode in rows:
        if patient_id and event.patient_id != patient_id:
            continue
        if department and (not episode or episode.department != department):
            continue
        if doctor_id and (not episode or episode.doctor_id != doctor_id):
            continue

        result.append(
            {
                "event_id": str(event.event_id),
                "direction": event.direction,
                "phone_number": event.phone_number,
                "message_text": event.message_text,
                "status": event.status,
                "received_at": event.received_at.isoformat() if event.received_at else None,
                "patient_id": str(patient.patient_id) if patient else None,
                "patient_ref": patient.patient_ref if patient else None,
                "patient_name": patient.full_name if patient else None,
                "episode_id": str(episode.episode_id) if episode else None,
                "episode_ref": episode.episode_ref if episode else None,
                "department": episode.department if episode else None,
                "doctor_id": (
                    str(episode.doctor_id) if episode and episode.doctor_id else None
                ),
                "needs_review": event.patient_id is None,
                "attention_flag": bool(event.attention_flag),
                "attention_note": event.attention_note,
                "attention_updated_at": (
                    event.attention_updated_at.isoformat()
                    if event.attention_updated_at
                    else None
                ),
            }
        )

    return result


@router.patch("/events/{event_id}/assign", dependencies=[Depends(get_current_user)])
def assign_inbound_message(
        event_id: uuid.UUID,
        payload: AssignInboundMessage,
        db: Session = Depends(get_db),
):
    """Manually link an inbound WhatsApp event after staff review."""
    event = db.get(WhatsAppEvent, event_id)
    if not event:
        raise HTTPException(404, "WhatsApp event not found")
    if event.direction != "INBOUND":
        raise HTTPException(400, "Only inbound WhatsApp messages can be assigned")

    patient = db.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(404, "Selected patient not found")

    episode = None
    if payload.episode_id:
        episode = db.get(CareEpisode, payload.episode_id)
        if not episode:
            raise HTTPException(404, "Selected care episode not found")
        if episode.patient_id != patient.patient_id:
            raise HTTPException(400, "Selected care episode does not belong to this patient")

    event.patient_id = patient.patient_id
    event.episode_id = episode.episode_id if episode else None
    event.status = "ASSIGNED" if episode else "ASSIGNED_NO_EPISODE"
    try:
        db.commit()
        db.refresh(event)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, "Could not assign the WhatsApp message") from exc

    return {
        "event_id": str(event.event_id),
        "patient_id": str(patient.patient_id),
        "patient_ref": patient.patient_ref,
        "patient_name": patient.full_name,
        "episode_id": str(episode.episode_id) if episode else None,
        "episode_ref": episode.episode_ref if episode else None,
        "status": event.status,
    }


@router.patch("/events/{event_id}/attention", dependencies=[Depends(get_current_user)])
def update_attention_flag(
        event_id: uuid.UUID,
        payload: AttentionUpdate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    """Let authenticated staff flag or resolve a message for follow-up."""
    event = db.get(WhatsAppEvent, event_id)
    if not event:
        raise HTTPException(404, "WhatsApp event not found")
    if event.direction != "INBOUND":
        raise HTTPException(400, "Only inbound patient messages can be flagged for follow-up")
    if payload.attention_flag and not (payload.attention_note or "").strip():
        raise HTTPException(400, "Add a short staff note explaining why follow-up is needed")

    event.attention_flag = payload.attention_flag
    if payload.attention_flag:
        event.attention_note = (payload.attention_note or "").strip()
    event.attention_updated_at = datetime.now(timezone.utc)
    event.attention_updated_by = current_user.user_id

    try:
        db.commit()
        db.refresh(event)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, "Could not update the message attention flag") from exc

    return {
        "event_id": str(event.event_id),
        "attention_flag": bool(event.attention_flag),
        "attention_note": event.attention_note,
        "attention_updated_at": (
            event.attention_updated_at.isoformat() if event.attention_updated_at else None
        ),
    }


@router.get("/webhook")
def verify_webhook(
        mode: str | None = Query(None, alias="hub.mode"),
        verify_token: str | None = Query(None, alias="hub.verify_token"),
        challenge: str | None = Query(None, alias="hub.challenge"),
):
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if (
            mode == "subscribe"
            and expected
            and hmac.compare_digest(verify_token or "", expected)
    ):
        return Response(content=challenge or "", media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not app_secret:
        raise HTTPException(503, "WhatsApp webhook is not configured")

    expected = "sha256=" + hmac.new(
        app_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON payload") from exc

    status_rank = {"SENT": 1, "DELIVERED": 2, "READ": 3}
    media_to_process: list[tuple[uuid.UUID, str, str | None]] = []

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {
                    contact.get("wa_id"): contact.get("profile", {}).get("name")
                    for contact in value.get("contacts", [])
                }

                for msg in value.get("messages", []):
                    wa_id = msg.get("from", "")
                    provider_id = msg.get("id")
                    message_type = msg.get("type", "unknown")
                    image_info = msg.get("image", {}) if message_type == "image" else {}
                    media_id = image_info.get("id")
                    caption = image_info.get("caption")

                    if provider_id and db.scalar(
                        select(WhatsAppEvent.event_id).where(
                            WhatsAppEvent.provider_message_id == provider_id
                        )
                    ):
                        continue

                    sender_key = sender_mobile_key(wa_id)
                    candidates = db.scalars(select(Patient)).all()
                    matches = (
                        [
                            patient
                            for patient in candidates
                            if sender_mobile_key(patient.mobile_number) == sender_key
                        ]
                        if sender_key
                        else []
                    )
                    # Resolve shared mobile numbers deterministically: prefer the
                    # latest DISCHARGE patient, then latest patient_id/created_at.
                    matches.sort(key=lambda p: (p.created_at or datetime.min.replace(tzinfo=timezone.utc), str(p.patient_id)), reverse=True)
                    discharge_matches = [p for p in matches if p.registration_flow == "DISCHARGE"]
                    patient = (discharge_matches or matches)[0] if matches else None

                    episode = None
                    if patient:
                        episode = db.scalars(
                            select(CareEpisode)
                            .where(CareEpisode.patient_id == patient.patient_id)
                            .order_by(CareEpisode.created_at.desc(), CareEpisode.episode_id.desc())
                            .limit(1)
                        ).first()

                    if message_type == "image":
                        text_body = caption or "Image received via WhatsApp"
                    else:
                        text_body = msg.get("text", {}).get("body") or (
                            f"Incoming WhatsApp message type: {message_type}"
                        )

                    event_id = uuid.uuid4()
                    event_values = {
                        "event_id": event_id,
                        "patient_id": patient.patient_id if patient else None,
                        "episode_id": episode.episode_id if episode else None,
                        "direction": "INBOUND",
                        "phone_number": wa_id,
                        "message_text": text_body[:4000],
                        "provider_message_id": provider_id,
                        "status": "RECEIVED" if patient else "NEEDS_REVIEW",
                        "contact_name": contacts.get(wa_id),
                        "received_at": datetime.now(timezone.utc),
                    }

                    statement = pg_insert(WhatsAppEvent).values(**event_values)
                    if provider_id:
                        statement = statement.on_conflict_do_nothing(
                            index_elements=[WhatsAppEvent.provider_message_id]
                        )
                    db.execute(statement)

                    if media_id:
                        # Resolve the persisted event in case a concurrent
                        # webhook delivery inserted it first.
                        event = db.get(WhatsAppEvent, event_id)
                        if event is None and provider_id:
                            event = db.scalar(
                                select(WhatsAppEvent).where(
                                    WhatsAppEvent.provider_message_id == provider_id
                                )
                            )

                        if event and not db.scalar(
                            select(WhatsAppMedia.media_record_id).where(
                                WhatsAppMedia.provider_media_id == media_id
                            )
                        ):
                            media_record_id = uuid.uuid4()
                            media_mime = image_info.get("mime_type") or "application/octet-stream"
                            media_row = pg_insert(WhatsAppMedia).values(
                                media_record_id=media_record_id,
                                event_id=event.event_id,
                                provider_media_id=media_id,
                                mime_type=media_mime,
                                caption=caption,
                                status="PENDING",
                            ).on_conflict_do_nothing(
                                index_elements=[WhatsAppMedia.provider_media_id]
                            )
                            media_insert_result = db.execute(media_row)
                            # A concurrent webhook may have inserted this media
                            # already. Only process the row created by this insert.
                            if media_insert_result.rowcount == 1:
                                media_to_process.append(
                                    (media_record_id, media_id, image_info.get("sha256"))
                                )

                for callback in value.get("statuses", []):
                    provider_id = callback.get("id")
                    new_status = str(callback.get("status", "")).upper()
                    if not provider_id or new_status not in {
                        "SENT", "DELIVERED", "READ", "FAILED"
                    }:
                        continue

                    event = db.scalar(
                        select(WhatsAppEvent).where(
                            WhatsAppEvent.provider_message_id == provider_id
                        )
                    )
                    if not event or event.direction != "OUTBOUND":
                        continue

                    current_status = (event.status or "").upper()

                    if current_status == "READ":
                        applied_status = "READ"
                    elif current_status == "FAILED":
                        applied_status = "FAILED"
                    elif new_status == "FAILED":
                        if current_status in {"SENT", "DELIVERED"}:
                            event.status = "FAILED"
                        applied_status = (event.status or current_status).upper()
                    else:
                        if status_rank.get(new_status, 0) > status_rank.get(current_status, 0):
                            event.status = new_status
                        applied_status = (event.status or current_status).upper()

                    notification = db.scalar(
                        select(WhatsAppNotification).where(
                            WhatsAppNotification.provider_message_id == provider_id
                        )
                    )
                    if notification and applied_status in {
                        "SENT", "DELIVERED", "READ", "FAILED"
                    }:
                        notification.status = applied_status
                        notification.updated_at = datetime.now(timezone.utc)

                        if applied_status == "FAILED":
                            errors = callback.get("errors") or []
                            if errors:
                                first_error = errors[0]
                                details = []
                                error_code = first_error.get("code")
                                error_message = first_error.get("message")
                                if error_code is not None:
                                    details.append(f"Provider code: {error_code}")
                                if error_message:
                                    details.append(str(error_message)[:500])
                                if details:
                                    notification.error_note = "; ".join(details)

        # Commit events and PENDING media metadata before contacting external
        # services, so a storage failure does not erase the inbound message.
        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed; retry the delivery",
        ) from exc

    # Process stored media after the database commit. Image failures are recorded
    # separately and do not cause Meta to retry the whole webhook indefinitely.
    for media_record_id, media_id, expected_sha256 in media_to_process:
        try:
            stored = store_whatsapp_image(media_id, expected_sha256)
            media_row = db.get(WhatsAppMedia, media_record_id)
            if media_row:
                media_row.s3_key = stored["s3_key"]
                media_row.mime_type = stored["mime_type"]
                media_row.byte_size = stored["byte_size"]
                media_row.sha256 = stored["sha256"]
                media_row.status = "STORED"
                media_row.error_note = None
                db.commit()
        except WhatsAppMediaError as exc:
            db.rollback()
            media_row = db.get(WhatsAppMedia, media_record_id)
            if media_row:
                media_row.status = "FAILED"
                media_row.error_note = str(exc)[:500]
                db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Media status update failed; retry the delivery",
            ) from exc

    return {"status": "ok"}

@router.get("/media")
def list_whatsapp_media(
    patient_id: uuid.UUID | None = Query(None),
    event_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List stored WhatsApp images for an authenticated Care Plus staff user.

    Image URLs are short-lived presigned S3 URLs. The bucket remains private.
    """
    if current_user.role not in {"ADMIN", "STAFF"}:
        raise HTTPException(
            status_code=403,
            detail="Staff access is required to view WhatsApp images",
        )
    statement = (
        select(WhatsAppMedia, WhatsAppEvent)
        .join(WhatsAppEvent, WhatsAppMedia.event_id == WhatsAppEvent.event_id)
        .where(
            WhatsAppMedia.status == "STORED",
            WhatsAppMedia.s3_key.is_not(None),
        )
    )

    if patient_id is not None:
        statement = statement.where(WhatsAppEvent.patient_id == patient_id)

    if event_id is not None:
        statement = statement.where(WhatsAppEvent.event_id == event_id)

    rows = db.execute(
        statement.order_by(WhatsAppMedia.created_at.desc()).limit(100)
    ).all()

    result = []
    for media, event in rows:
        try:
            url = create_presigned_image_url(media.s3_key)
        except WhatsAppMediaError as exc:
            raise HTTPException(
                status_code=503,
                detail="Image storage is temporarily unavailable",
            ) from exc

        result.append({
            "media_record_id": str(media.media_record_id),
            "event_id": str(event.event_id),
            "patient_id": str(event.patient_id) if event.patient_id else None,
            "direction": event.direction,
            "caption": media.caption,
            "mime_type": media.mime_type,
            "byte_size": media.byte_size,
            "created_at": media.created_at.isoformat() if media.created_at else None,
            "url": url,
            "url_expires_in": 300,
        })

    return {"items": result}
