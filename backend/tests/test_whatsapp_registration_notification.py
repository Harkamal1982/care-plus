import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

load_dotenv(Path.cwd() / "backend" / ".env", override=False)

from app.db.models import WhatsAppNotification
from app.services import whatsapp_notifications as service


class FakeResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, reserve=True, fail_commit=False):
        self.reserve = reserve
        self.fail_commit = fail_commit
        self.execute_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self.added = []
        self.notification = SimpleNamespace(
            notification_id=uuid.uuid4(),
            status="PENDING",
            provider_message_id=None,
            error_note=None,
        )

    def execute(self, statement):
        self.execute_calls += 1
        # The first statement reserves the notification; later statements
        # update its status.
        if self.execute_calls == 1:
            value = self.notification.notification_id if self.reserve else None
            return FakeResult(value)
        return FakeResult()

    def scalar(self, statement):
        return self.notification

    def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise SQLAlchemyError("simulated commit failure")

    def rollback(self):
        self.rollback_calls += 1

    def add(self, obj):
        self.added.append(obj)


def patient():
    return SimpleNamespace(
        patient_id=uuid.uuid4(),
        full_name="Synthetic Test Patient",
        mobile_number="9876543210",
    )


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.is_error = status_code >= 400

    def json(self):
        return self.payload


class FakeAsyncClient:
    response = None
    error = None
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        type(self).calls.append((url, kwargs))
        if type(self).error:
            raise type(self).error
        return type(self).response


@pytest.fixture(autouse=True)
def mock_whatsapp(monkeypatch):
    monkeypatch.setenv("WHATSAPP_REGISTRATION_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token-not-real")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "test-phone-id")
    monkeypatch.setenv("WHATSAPP_API_VERSION", "v26.0")
    FakeAsyncClient.response = FakeResponse(
        200, {"messages": [{"id": "wamid.test-message"}]}
    )
    FakeAsyncClient.error = None
    FakeAsyncClient.calls = []
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)


def test_success_sends_existing_template_and_records_event():
    db = FakeDB()

    result = asyncio.run(service.send_registration_template(db, patient()))

    assert result["status"] == "SENT"
    assert len(FakeAsyncClient.calls) == 1

    _, request = FakeAsyncClient.calls[0]
    body = request["json"]
    assert body["type"] == "template"
    assert body["template"]["name"] == "careplus_patient_followup"
    assert body["template"]["language"]["code"] == "en"
    assert body["template"]["components"][0]["parameters"][0]["text"] == (
        "Synthetic Test Patient"
    )
    assert len(db.added) == 1
    assert db.added[0].provider_message_id == "wamid.test-message"


def test_duplicate_registration_notification_is_not_sent():
    db = FakeDB(reserve=False)

    result = asyncio.run(service.send_registration_template(db, patient()))

    assert result["status"] == "DUPLICATE_SKIPPED"
    assert FakeAsyncClient.calls == []


def test_provider_rejection_is_recorded_as_failed():
    db = FakeDB()
    FakeAsyncClient.response = FakeResponse(
        400, {"error": {"code": 132000}}
    )

    result = asyncio.run(service.send_registration_template(db, patient()))

    assert result["status"] == "FAILED"
    assert len(FakeAsyncClient.calls) == 1
    assert db.execute_calls >= 2


def test_network_failure_is_unknown_and_not_retried():
    db = FakeDB()
    FakeAsyncClient.error = httpx.ConnectError("simulated test failure")

    result = asyncio.run(service.send_registration_template(db, patient()))

    assert result["status"] == "UNKNOWN"
    assert len(FakeAsyncClient.calls) == 1
    assert db.execute_calls >= 2


def test_notifications_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WHATSAPP_REGISTRATION_NOTIFICATIONS_ENABLED", raising=False)
    db = FakeDB()

    result = asyncio.run(service.send_registration_template(db, patient()))

    assert result["status"] == "DISABLED"
    assert FakeAsyncClient.calls == []
    assert db.execute_calls == 0
