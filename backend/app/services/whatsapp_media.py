"""Download inbound WhatsApp images and store them privately in Amazon S3."""

import hashlib
import os
import uuid

import boto3
import httpx


ALLOWED_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class WhatsAppMediaError(Exception):
    """A WhatsApp image could not be stored."""


def store_whatsapp_image(
    media_id: str,
    expected_sha256: str | None = None,
) -> dict:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    api_version = os.getenv("WHATSAPP_API_VERSION", "v23.0")
    bucket = os.getenv("WHATSAPP_MEDIA_S3_BUCKET")
    region = os.getenv("AWS_REGION")

    if not all((access_token, bucket, region)):
        raise WhatsAppMediaError(
            "WhatsApp token or S3 storage configuration is missing"
        )

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            metadata_response = client.get(
                f"https://graph.facebook.com/{api_version}/{media_id}",
                headers=headers,
            )
            metadata_response.raise_for_status()
            metadata = metadata_response.json()

            media_url = metadata.get("url")
            mime_type = metadata.get("mime_type", "").split(";")[0].lower()
            reported_size = metadata.get("file_size")

            if not media_url:
                raise WhatsAppMediaError("Meta did not return a media URL")

            if mime_type not in ALLOWED_MIME_TYPES:
                raise WhatsAppMediaError("Unsupported image MIME type")

            if reported_size is not None and int(reported_size) > MAX_IMAGE_BYTES:
                raise WhatsAppMediaError("Image exceeds the maximum size")

            # Meta media download URLs must remain on Meta's HTTPS hosts.
            from urllib.parse import urlparse

            parsed = urlparse(media_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {
                    "lookaside.fbsbx.com",
                    "lookaside.facebook.com",
                    "graph.facebook.com",
                }
            ):
                raise WhatsAppMediaError("Unexpected media download host")

            with client.stream("GET", media_url, headers=headers) as response:
                response.raise_for_status()

                chunks = []
                total_size = 0

                for chunk in response.iter_bytes():
                    total_size += len(chunk)
                    if total_size > MAX_IMAGE_BYTES:
                        raise WhatsAppMediaError(
                            "Downloaded image exceeds the maximum size"
                        )
                    chunks.append(chunk)

            content = b"".join(chunks)

        if not content:
            raise WhatsAppMediaError("Downloaded image is empty")

        digest = hashlib.sha256(content).hexdigest()

        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise WhatsAppMediaError("Image SHA-256 verification failed")

        extension = ALLOWED_MIME_TYPES[mime_type]
        s3_key = f"whatsapp/inbound/{uuid.uuid4()}.{extension}"

        s3 = boto3.client("s3", region_name=region)

        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=content,
            ContentType=mime_type,
            ServerSideEncryption="AES256",
        )

        return {
            "s3_key": s3_key,
            "mime_type": mime_type,
            "byte_size": len(content),
            "sha256": digest,
        }

    except WhatsAppMediaError:
        raise
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise WhatsAppMediaError(
            "Failed to retrieve WhatsApp image from Meta"
        ) from exc
    except Exception as exc:
        raise WhatsAppMediaError(
            "Failed to store WhatsApp image in S3"
        ) from exc


def create_presigned_image_url(s3_key: str) -> str:
    bucket = os.getenv("WHATSAPP_MEDIA_S3_BUCKET")
    region = os.getenv("AWS_REGION")

    if not bucket or not region:
        raise WhatsAppMediaError("S3 storage configuration is missing")

    s3 = boto3.client("s3", region_name=region)

    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=300,
    )
