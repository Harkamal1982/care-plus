import hashlib
from contextlib import contextmanager

import pytest
import httpx

from app.services import whatsapp_media as media


IMAGE_BYTES = b"synthetic-test-image"
IMAGE_SHA256 = hashlib.sha256(IMAGE_BYTES).hexdigest()


class FakeResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self.payload = payload or {}
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "synthetic HTTP error",
                request=httpx.Request("GET", "https://example.test"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self.payload

    def iter_bytes(self):
        yield self.content


class FakeHttpClient:
    metadata = None
    download = None
    metadata_error = None
    download_error = None
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        type(self).calls.append(("get", url))
        if type(self).metadata_error:
            raise type(self).metadata_error
        return type(self).metadata

    @contextmanager
    def stream(self, method, url, **kwargs):
        type(self).calls.append(("stream", url))
        if type(self).download_error:
            raise type(self).download_error
        yield type(self).download


class FakeS3:
    def __init__(self):
        self.put_calls = []
        self.presign_calls = []
        self.fail_put = False

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        if self.fail_put:
            raise RuntimeError("synthetic S3 failure")

    def generate_presigned_url(self, **kwargs):
        self.presign_calls.append(kwargs)
        return "https://example.test/presigned-image"


@pytest.fixture(autouse=True)
def configure_mocks(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("WHATSAPP_API_VERSION", "v23.0")
    monkeypatch.setenv("WHATSAPP_MEDIA_S3_BUCKET", "synthetic-test-bucket")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")

    FakeHttpClient.metadata = FakeResponse(
        payload={
            "url": "https://lookaside.fbsbx.com/synthetic-image",
            "mime_type": "image/jpeg",
            "file_size": len(IMAGE_BYTES),
        }
    )
    FakeHttpClient.download = FakeResponse(content=IMAGE_BYTES)
    FakeHttpClient.metadata_error = None
    FakeHttpClient.download_error = None
    FakeHttpClient.calls = []

    s3 = FakeS3()
    monkeypatch.setattr(media.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(media.boto3, "client", lambda *args, **kwargs: s3)
    return s3


def test_store_image_uploads_private_encrypted_object(configure_mocks):
    result = media.store_whatsapp_image("synthetic-media-id", IMAGE_SHA256)

    assert result["mime_type"] == "image/jpeg"
    assert result["byte_size"] == len(IMAGE_BYTES)
    assert result["sha256"] == IMAGE_SHA256
    assert result["s3_key"].startswith("whatsapp/inbound/")
    assert result["s3_key"].endswith(".jpg")

    assert len(configure_mocks.put_calls) == 1
    upload = configure_mocks.put_calls[0]
    assert upload["Bucket"] == "synthetic-test-bucket"
    assert upload["Body"] == IMAGE_BYTES
    assert upload["ServerSideEncryption"] == "AES256"


def test_rejects_untrusted_download_url(configure_mocks):
    FakeHttpClient.metadata = FakeResponse(
        payload={
            "url": "https://attacker.example/image.jpg",
            "mime_type": "image/jpeg",
            "file_size": len(IMAGE_BYTES),
        }
    )

    with pytest.raises(media.WhatsAppMediaError, match="Unexpected media"):
        media.store_whatsapp_image("synthetic-media-id")

    assert configure_mocks.put_calls == []


def test_rejects_unsupported_mime_type(configure_mocks):
    FakeHttpClient.metadata = FakeResponse(
        payload={
            "url": "https://lookaside.fbsbx.com/synthetic-image",
            "mime_type": "image/svg+xml",
            "file_size": len(IMAGE_BYTES),
        }
    )

    with pytest.raises(media.WhatsAppMediaError, match="Unsupported image MIME"):
        media.store_whatsapp_image("synthetic-media-id")

    assert configure_mocks.put_calls == []


def test_rejects_reported_oversized_image(configure_mocks):
    FakeHttpClient.metadata = FakeResponse(
        payload={
            "url": "https://lookaside.fbsbx.com/synthetic-image",
            "mime_type": "image/jpeg",
            "file_size": media.MAX_IMAGE_BYTES + 1,
        }
    )

    with pytest.raises(media.WhatsAppMediaError, match="maximum size"):
        media.store_whatsapp_image("synthetic-media-id")

    assert configure_mocks.put_calls == []


def test_rejects_streamed_oversized_image(configure_mocks):
    FakeHttpClient.metadata = FakeResponse(
        payload={
            "url": "https://lookaside.fbsbx.com/synthetic-image",
            "mime_type": "image/jpeg",
            "file_size": media.MAX_IMAGE_BYTES,
        }
    )
    FakeHttpClient.download = FakeResponse(
        content=b"x" * (media.MAX_IMAGE_BYTES + 1)
    )

    with pytest.raises(media.WhatsAppMediaError, match="exceeds the maximum size"):
        media.store_whatsapp_image("synthetic-media-id")

    assert configure_mocks.put_calls == []


def test_rejects_sha256_mismatch(configure_mocks):
    with pytest.raises(media.WhatsAppMediaError, match="SHA-256"):
        media.store_whatsapp_image("synthetic-media-id", "0" * 64)

    assert configure_mocks.put_calls == []


def test_reports_meta_download_failure(configure_mocks):
    FakeHttpClient.metadata_error = httpx.ConnectError(
        "synthetic connection failure"
    )

    with pytest.raises(media.WhatsAppMediaError, match="retrieve"):
        media.store_whatsapp_image("synthetic-media-id")

    assert configure_mocks.put_calls == []


def test_reports_s3_upload_failure(configure_mocks):
    configure_mocks.fail_put = True

    with pytest.raises(media.WhatsAppMediaError, match="store"):
        media.store_whatsapp_image("synthetic-media-id")


def test_presigned_url_is_short_lived(configure_mocks):
    url = media.create_presigned_image_url("whatsapp/inbound/test.jpg")

    assert url == "https://example.test/presigned-image"
    assert configure_mocks.presign_calls == [
        {
            "ClientMethod": "get_object",
            "Params": {
                "Bucket": "synthetic-test-bucket",
                "Key": "whatsapp/inbound/test.jpg",
            },
            "ExpiresIn": 300,
        }
    ]


def test_missing_s3_configuration_is_rejected(monkeypatch):
    monkeypatch.delenv("WHATSAPP_MEDIA_S3_BUCKET", raising=False)

    with pytest.raises(media.WhatsAppMediaError, match="configuration"):
        media.create_presigned_image_url("whatsapp/inbound/test.jpg")
