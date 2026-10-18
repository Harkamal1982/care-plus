CREATE TABLE IF NOT EXISTS whatsapp_media (
    media_record_id UUID PRIMARY KEY,
    event_id UUID NOT NULL
        REFERENCES whatsapp_events(event_id) ON DELETE CASCADE,
    provider_media_id VARCHAR(200) NOT NULL UNIQUE,
    s3_key VARCHAR(1024) UNIQUE,
    mime_type VARCHAR(100) NOT NULL,
    byte_size BIGINT,
    sha256 VARCHAR(64),
    caption TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    error_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_whatsapp_media_event_id
    ON whatsapp_media(event_id);
