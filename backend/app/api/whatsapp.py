
"""WhatsApp Cloud API integration.

Configure credentials in backend/.env before enabling outbound delivery.
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
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import CareEpisode, Patient, WhatsAppEvent

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


class SendMessage(BaseModel):
    patient_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


def normalize_indian_mobile(value: str) -> str:
    """Return an Indian mobile number as 91 + 10 digits.

    Accepted examples:
      9878446888
      +919878446888
      919878446888
      09878446888

    Raises ValueError for unsupported formats.
    """
    digits = "".join(ch for ch in value if ch.isdigit())

    if len(digits) == 10:
        mobile = digits
    elif len(digits) == 12 and digits.startswith("91"):
        mobile = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        mobile = digits[1:]
    else:
        raise ValueError("Expected a 10-digit Indian mobile number, optionally prefixed by 0 or 91.")

    # Indian mobile numbers normally begin with digits 6, 7, 8, or 9.
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
                400,
                "The selected episode does not belong to this patient",
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
        raise HTTPException(
            400,
            f"Patient mobile number is invalid: {exc}",
        ) from exc

    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": payload.message,
        },
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
            error_message = error.get("message", "unknown error")
            raise HTTPException(
                response.status_code,
                f"WhatsApp API rejected message"
                f"{f' (code {error_code})' if error_code else ''}: "
                f"{error_message}",
            )

    except httpx.HTTPError as exc:
        raise HTTPException(
            502,
            f"WhatsApp API request failed: {exc}",
        ) from exc

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

    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "event_id": str(event.event_id),
        "status": "SENT",
        "provider_message_id": wamid,
        "recipient": to,
    }


@router.get("/progress", dependencies=[Depends(get_current_user)])
def progress(
        db: Session = Depends(get_db),
        department: str | None = None,
        doctor_id: uuid.UUID | None = None,
        patient_id: uuid.UUID | None = None,
):
    stmt = (
        select(WhatsAppEvent, Patient, CareEpisode)
        .outerjoin(Patient, Patient.patient_id == WhatsAppEvent.patient_id)
        .outerjoin(
            CareEpisode,
            CareEpisode.episode_id == WhatsAppEvent.episode_id,
            )
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
                "received_at": (
                    event.received_at.isoformat()
                    if event.received_at
                    else None
                ),
                "patient_id": str(patient.patient_id) if patient else None,
                "patient_ref": patient.patient_ref if patient else None,
                "patient_name": patient.full_name if patient else None,
                "episode_id": str(episode.episode_id) if episode else None,
                "episode_ref": episode.episode_ref if episode else None,
                "department": episode.department if episode else None,
                "doctor_id": (
                    str(episode.doctor_id)
                    if episode and episode.doctor_id
                    else None
                ),
                "needs_review": event.patient_id is None,
            }
        )

    return result


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
async def receive_webhook(
        request: Request,
        db: Session = Depends(get_db),
):
    raw = await request.body()
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not app_secret:
        raise HTTPException(503, "WhatsApp webhook is not configured")

    expected = "sha256=" + hmac.new(
        app_secret.encode(),
        raw,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid JSON payload") from exc

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                c.get("wa_id"): c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }

            for msg in value.get("messages", []):
                wa_id = msg.get("from", "")
                provider_id = msg.get("id")

                # Ignore webhook retries for already-recorded provider messages.
                if provider_id and db.scalar(
                        select(WhatsAppEvent.event_id).where(
                            WhatsAppEvent.provider_message_id == provider_id
                        )
                ):
                    continue

                sender_key = sender_mobile_key(wa_id)
                candidates = db.scalars(select(Patient)).all()

                matches = []
                if sender_key:
                    matches = [
                        patient
                        for patient in candidates
                        if sender_mobile_key(patient.mobile_number) == sender_key
                    ]

                # Never guess when multiple patient records share a number.
                patient = matches[0] if len(matches) == 1 else None

                episode = None
                if patient:
                    active_eps = db.scalars(
                        select(CareEpisode)
                        .where(
                            CareEpisode.patient_id == patient.patient_id,
                            CareEpisode.status == "ACTIVE",
                            )
                        .limit(2)
                    ).all()

                    if len(active_eps) == 1:
                        episode = active_eps[0]

                text_body = (
                        msg.get("text", {}).get("body")
                        or f"Incoming WhatsApp message type: {msg.get('type', 'unknown')}"
                )

                db.add(
                    WhatsAppEvent(
                        patient_id=patient.patient_id if patient else None,
                        episode_id=episode.episode_id if episode else None,
                        direction="INBOUND",
                        phone_number=wa_id,
                        message_text=text_body[:4000],
                        provider_message_id=provider_id,
                        status="RECEIVED" if patient else "NEEDS_REVIEW",
                        contact_name=contacts.get(wa_id),
                        received_at=datetime.now(timezone.utc),
                    )
                )

            for st in value.get("statuses", []):
                provider_id = st.get("id")
                if provider_id:
                    event = db.scalar(
                        select(WhatsAppEvent).where(
                            WhatsAppEvent.provider_message_id == provider_id
                        )
                    )
                    if event:
                        event.status = str(st.get("status", event.status)).upper()

    db.commit()
    return {"status": "ok"}
