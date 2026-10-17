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
    def __init__(self, event=None, duplicate=False, fail_commit=False):
        self.event = event
        self.duplicate = duplicate
        self.fail_commit = fail_commit
        self.execute_calls = []
        self.commit_calls = 0
        self.rollback_called = False

    def scalar(self, statement):
        if self.duplicate:
            return "existing-event-id"
        return self.event

    def execute(self, statement):
        self.execute_calls.append(statement)

    def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise SQLAlchemyError("simulated database failure")

    def rollback(self):
        self.rollback_called = True


def status_payload(provider_id, status):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": provider_id, "status": status}
                            ]
                        }
                    }
                ]
            }
        ]
    }


def run_webhook(monkeypatch, payload, db):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    return asyncio.run(receive_webhook(FakeRequest(payload), db))


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
                                    "text": {"body": "Test message"},
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
    event = SimpleNamespace(direction="OUTBOUND", status="READ")
    db = FakeDB(event=event)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-read", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "READ"
    assert db.commit_calls == 1


def test_repeated_delivered_callback_is_safe(monkeypatch):
    event = SimpleNamespace(direction="OUTBOUND", status="DELIVERED")
    db = FakeDB(event=event)

    result = run_webhook(
        monkeypatch,
        status_payload("wamid-delivered", "delivered"),
        db,
    )

    assert result == {"status": "ok"}
    assert event.status == "DELIVERED"
    assert db.commit_calls == 1


def test_database_error_rolls_back_and_returns_http_error(monkeypatch):
    event = SimpleNamespace(direction="OUTBOUND", status="SENT")
    db = FakeDB(event=event, fail_commit=True)

    with pytest.raises(HTTPException) as exc_info:
        run_webhook(
            monkeypatch,
            status_payload("wamid-db-error", "delivered"),
            db,
        )

    assert exc_info.value.status_code == 500
    assert db.rollback_called is True
