import uuid
from datetime import date, datetime, time
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, Time, JSON, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base

class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_ref: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(20), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_flow: Mapped[str] = mapped_column(String(30), default="DISCHARGE", nullable=False)
    visit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    surgery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_surgery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    department: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    followup_status: Mapped[str] = mapped_column(String(40), default="PLANNED", nullable=False)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.doctor_id"), nullable=True)
    doctor: Mapped["Doctor | None"] = relationship(back_populates="patients")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    episodes: Mapped[list["CareEpisode"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_patients_mobile_number", "mobile_number"), Index("ix_patients_full_name", "full_name"))


class Doctor(Base):
    __tablename__ = "doctors"
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    department: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    patients: Mapped[list["Patient"]] = relationship(back_populates="doctor")
    __table_args__ = (UniqueConstraint("full_name", "department", name="uq_doctors_name_department"),)


class CareEpisode(Base):
    __tablename__ = "care_episodes"
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_ref: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False, index=True)
    # hospital_name retained for backward compatibility with existing records; UI is single-hospital.
    hospital_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str] = mapped_column(String(80), default="Other", nullable=False)
    treating_doctor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.doctor_id"), nullable=True)
    admission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discharge_date: Mapped[date] = mapped_column(Date, nullable=False)
    care_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    care_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_for_care: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    patient: Mapped[Patient] = relationship(back_populates="episodes")
    tasks: Mapped[list["CareTask"]] = relationship(back_populates="episode", cascade="all, delete-orphan")

class CareTask(Base):
    __tablename__ = "care_tasks"
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("care_episodes.episode_id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Legacy columns remain until a later release to preserve old data/integrations.
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    repeat_daily: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    selected_slots: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    episode: Mapped[CareEpisode] = relationship(back_populates="tasks")

class AlertLog(Base):
    __tablename__ = "alert_logs"
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("care_tasks.task_id"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="PREVIEW", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PREVIEW_ONLY", nullable=False)
    message_preview: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("task_id", "scheduled_date", "slot", name="uq_alert_task_date_slot"),)

class FollowupReminderLog(Base):
    __tablename__ = "followup_reminder_logs"
    reminder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False, index=True)
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    reminder_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="PREVIEW", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PREVIEW_ONLY", nullable=False)
    message_preview: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("patient_id", "reminder_type", "appointment_date", name="uq_followup_patient_type_date"),)


class User(Base):
    __tablename__ = "staff_users"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="STAFF", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FollowupCallNote(Base):
    __tablename__ = "followup_call_notes"
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False, index=True)
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_users.user_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    call_outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="CONTACTED")
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    next_followup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_surgery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeletionAuditLog(Base):
    __tablename__ = "deletion_audit_logs"
    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_users.user_id"), nullable=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_label: Mapped[str] = mapped_column(String(250), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

class WhatsAppEvent(Base):
    __tablename__ = "whatsapp_events"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=True, index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("care_episodes.episode_id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    contact_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RECEIVED")
    attention_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    attention_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attention_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attention_updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff_users.user_id"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)



class WhatsAppMedia(Base):
    """Metadata for an inbound WhatsApp image stored privately in S3."""

    __tablename__ = "whatsapp_media"

    media_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_events.event_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_media_id: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True
    )
    s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default="PENDING"
    )
    error_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WhatsAppNotification(Base):
    __tablename__ = "whatsapp_notifications"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        unique=True,
    )
    error_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "notification_type",
            name="uq_whatsapp_notification_patient_type",
        ),
    )
