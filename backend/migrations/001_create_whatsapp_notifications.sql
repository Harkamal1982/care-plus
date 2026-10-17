CREATE TABLE IF NOT EXISTS whatsapp_notifications (
    notification_id UUID PRIMARY KEY,
    patient_id UUID NOT NULL REFERENCES patients(patient_id),
    notification_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    provider_message_id VARCHAR(200) UNIQUE,
    error_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_whatsapp_notification_patient_type
        UNIQUE (patient_id, notification_type)
);
