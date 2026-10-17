
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

load_dotenv(Path.cwd() / "backend" / ".env", override=False)

from app.api.whatsapp import receive_webhook
from app.db.models import WhatsAppEvent, WhatsAppNotification


APP_SECRET = "unit-test-app-secret"


class FakeRequest:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()
        signature = hmac.new(
            APP_SECRET.encode(),
            self.raw,
            hashlib.sha256,
        ).hexdigest()
        self.headers = {"X-Hub-Signature-256": f"sha256={signature}"}

    async def body(self):
        return self.raw


class FakeDB:
    def __init__(
            self,
            event=None,
            notification=None,
            duplicate=False,
            fail_commit=False,
    ):
        self.event = event
        self.notification = notification
        self.duplicate = duplicate
        self.fail_commit = fail_commit
        self.execute_calls = []
        self.commit_calls = 0
        self.rollback_called = False

    def scalar(self, statement):
        # Identify the selected entity rather than relying on SQL text.
        for description in statement.column_descriptions:
            entity = description.get("entity")
            name = description.get("name")

            # Inbound-message duplicate check:
            # select(WhatsAppEvent.event_id)
            if entity is WhatsAppEvent and name == "event_id":
                return "existing-event-id" if self.duplicate else None

            # Outbound status callback:
            # select(WhatsAppEvent)
            if entity is WhatsAppEvent:
                return self.event

            # Registration notification lookup:
            # select(WhatsAppNotification)
            if entity is WhatsAppNotification:
                return self.notification

        return None

    def execute(self, statement):
        self.execute_calls.append(statement)

    def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise SQLAlchemyError("simulated database failure")

    def rollback(self):
        self.rollback_called = True


def status_payload(provider_id, status, errors=None):
    callback = {
        "id": provider_id,
        "status": status,
    }

    if errors is not None:
        callback["errors"] = errors

    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [callback],
                        }
                    }
                ]
            }
        ]
    }


def run_webhook(monkeypatch, payload, db):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    return asyncio.run(receive_webhook(FakeRequest(payload), db))


def make_event(status):
    return SimpleNamespace(
        direction="OUTBOUND",
        status=status,
    )


def make_notification(status):
    return SimpleNamespace(
        status=status,
        updated_at=None,
        error_note=None,
    )


def test_duplicate_inbound_message_is_skipped(monkeypatch):
    db = FakeDB(duplicate=True)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid-existing",
                                    "type": "text",
                                    "text": {"body": "Synthetic test message"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    result = run_webhook(monkeypatch, payload, db)

    assert result == {"status": "ok"}
    assert db.execute_calls == []
    assert db.commit_calls == 1


def test_delivered_callback_does_not_downgrade_read(monkeypatch):
    event = make_event("READ")
    notification = make_notification("READ")
    db = FakeDB(event=event, notification=notification)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-read", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "READ"
    assert notification.status == "READ"
    assert db.commit_calls == 1


def test_delivered_callback_updates_notification(monkeypatch):
    event = make_event("SENT")
    notification = make_notification("SENT")
    db = FakeDB(event=event, notification=notification)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-delivered", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "DELIVERED"
    assert notification.status == "DELIVERED"
    assert notification.updated_at is not None
    assert db.commit_calls == 1


def test_read_callback_updates_notification(monkeypatch):
    event = make_event("DELIVERED")
    notification = make_notification("DELIVERED")
    db = FakeDB(event=event, notification=notification)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-read-update", "read"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "READ"
    assert notification.status == "READ"
    assert notification.updated_at is not None
    assert db.commit_calls == 1


def test_failed_callback_updates_notification_error(monkeypatch):
    event = make_event("DELIVERED")
    notification = make_notification("DELIVERED")
    db = FakeDB(event=event, notification=notification)

    result = run_webhook(
        monkeypatch,
        status_payload(
            "wamid-failed",
            "failed",
            errors=[
                {
                    "code": 131026,
                    "message": "Synthetic delivery failure",
                }
            ],
        ),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "FAILED"
    assert notification.status == "FAILED"
    assert "131026" in notification.error_note
    assert "Synthetic delivery failure" in notification.error_note
    assert db.commit_calls == 1


def test_repeated_delivered_callback_is_safe(monkeypatch):
    event = make_event("DELIVERED")
    notification = make_notification("DELIVERED")
    db = FakeDB(event=event, notification=notification)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-delivered-repeat", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "DELIVERED"
    assert notification.status == "DELIVERED"
    assert db.commit_calls == 1


def test_unknown_provider_message_is_ignored(monkeypatch):
    db = FakeDB(event=None, notification=None)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-not-found", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert db.commit_calls == 1


def test_database_error_rolls_back_and_returns_http_error(monkeypatch):
    event = make_event("SENT")
    notification = make_notification("SENT")
    db = FakeDB(
        event=event,
        notification=notification,
        fail_commit=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        run_webhook(
            monkeypatch,
            status_payload("wamid-db-error", "delivered"),
            db,
        )

    assert exc_info.value.status_code == 500
    assert db.rollback_called is True
