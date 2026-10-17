
"""Safe, deduplicated WhatsApp template notifications."""

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.whatsapp import normalize_indian_mobile
from app.db.models import Patient, WhatsAppEvent, WhatsAppNotification

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "careplus_patient_followup"
NOTIFICATION_TYPE = "PATIENT_REGISTRATION"


def _set_status(
        db: Session,
        notification_id: uuid.UUID,
        status: str,
        error_note: str | None = None,
        provider_message_id: str | None = None,
) -> None:
    db.execute(
        update(WhatsAppNotification)
        .where(WhatsAppNotification.notification_id == notification_id)
        .values(
            status=status,
            error_note=error_note,
            provider_message_id=provider_message_id,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


async def send_registration_template(
        db: Session,
        patient: Patient,
) -> dict:
    """Attempt one template send after registration has committed.

    Sending is disabled unless
    WHATSAPP_REGISTRATION_NOTIFICATIONS_ENABLED=true.
    Ambiguous outcomes are never automatically retried.
    """
    enabled = (
            os.getenv("WHATSAPP_REGISTRATION_NOTIFICATIONS_ENABLED", "").lower()
            == "true"
    )
    if not enabled:
        return {"status": "DISABLED"}

    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not token or not phone_id:
        logger.warning(
            "Registration WhatsApp notification skipped: not configured"
        )
        return {"status": "SKIPPED_NOT_CONFIGURED"}

    try:
        recipient = normalize_indian_mobile(patient.mobile_number)
    except (TypeError, ValueError):
        logger.warning(
            "Registration WhatsApp notification skipped: invalid mobile"
        )
        return {"status": "SKIPPED_INVALID_PHONE"}

    notification_id = uuid.uuid4()

    # Reserve the one allowed attempt before making the external request.
    try:
        statement = (
            pg_insert(WhatsAppNotification)
            .values(
                notification_id=notification_id,
                patient_id=patient.patient_id,
                notification_type=NOTIFICATION_TYPE,
                status="PENDING",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    WhatsAppNotification.patient_id,
                    WhatsAppNotification.notification_type,
                ]
            )
            .returning(WhatsAppNotification.notification_id)
        )

        reserved_id = db.execute(statement).scalar_one_or_none()
        db.commit()

    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "Could not reserve registration WhatsApp notification"
        )
        return {"status": "ERROR"}

    if reserved_id is None:
        return {"status": "DUPLICATE_SKIPPED"}

    version = os.getenv("WHATSAPP_API_VERSION", "v26.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": patient.full_name,
                        }
                    ],
                }
            ],
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
                json=payload,
            )

    except httpx.HTTPError:
        logger.warning(
            "Registration WhatsApp request outcome is uncertain",
            exc_info=True,
        )
        try:
            _set_status(
                db,
                notification_id,
                "UNKNOWN",
                "Request outcome uncertain; automatic retry prohibited.",
            )
        except SQLAlchemyError:
            db.rollback()
            logger.exception(
                "Could not record uncertain WhatsApp outcome"
            )

        return {"status": "UNKNOWN"}

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.is_error:
        error_code = (data.get("error") or {}).get("code")
        note = f"WhatsApp API returned HTTP {response.status_code}"

        if error_code is not None:
            note += f", provider code {error_code}"

        # A 5xx response may not conclusively establish whether
        # the provider accepted the message.
        status = (
            "UNKNOWN" if response.status_code >= 500 else "FAILED"
        )

        if status == "UNKNOWN":
            note += (
                ". Acceptance is uncertain; "
                "automatic retry prohibited."
            )

        try:
            _set_status(
                db,
                notification_id,
                status,
                note,
            )
        except SQLAlchemyError:
            db.rollback()
            logger.exception(
                "Could not record WhatsApp API error"
            )

        return {"status": status}

    messages = data.get("messages") or []
    provider_id = messages[0].get("id") if messages else None

    if not provider_id:
        try:
            _set_status(
                db,
                notification_id,
                "UNKNOWN",
                "Provider response contained no message ID.",
            )
        except SQLAlchemyError:
            db.rollback()
            logger.exception(
                "Could not record unknown WhatsApp outcome"
            )

        return {"status": "UNKNOWN"}

    try:
        notification = db.scalar(
            select(WhatsAppNotification).where(
                WhatsAppNotification.notification_id == notification_id
            )
        )

        if notification is None:
            raise SQLAlchemyError(
                "Notification reservation disappeared"
            )

        notification.status = "SENT"
        notification.provider_message_id = provider_id
        notification.error_note = None

        db.add(
            WhatsAppEvent(
                patient_id=patient.patient_id,
                direction="OUTBOUND",
                phone_number=recipient,
                contact_name=patient.full_name,
                message_text=f"Approved template sent: {TEMPLATE_NAME}",
                provider_message_id=provider_id,
                status="SENT",
                received_at=datetime.now(timezone.utc),
            )
        )

        db.commit()

    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "WhatsApp accepted the template but local persistence failed"
        )

        try:
            _set_status(
                db,
                notification_id,
                "UNKNOWN",
                (
                    "Provider accepted request; local save failed. "
                    "Do not resend automatically."
                ),
            )
        except SQLAlchemyError:
            db.rollback()
            logger.exception(
                "Could not record post-send persistence failure"
            )

        return {"status": "UNKNOWN"}

    return {"status": "SENT"}
