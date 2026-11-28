"""Database models. The rules that protect people live here as constraints, so no screen
or job can get around them:

- one camera-registered face per user, and only after a liveness check
- an uploaded photo is kept only if it matched that camera face
- nothing is sent to the swap provider before the safety check passed
- every output is watermarked and C2PA-signed
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, LargeBinary, Numeric,
    String, Text, UniqueConstraint, create_engine, BigInteger, JSON, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def _id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(Timestamped, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    face: Mapped["Face | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class Face(Timestamped, Base):
    """The owner's own face, registered by live camera capture with a liveness check."""
    __tablename__ = "faces"
    __table_args__ = (
        CheckConstraint("source = 'camera'", name="face_camera_only"),
        CheckConstraint("age_check_passed", name="face_age_check"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="camera", nullable=False)
    liveness_challenge_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    liveness_passed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    age_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    user: Mapped[User] = relationship(back_populates="face")
    photos: Mapped[list["FacePhoto"]] = relationship(back_populates="face", cascade="all, delete-orphan",
                                                     order_by="FacePhoto.created_at")


class FacePhoto(Timestamped, Base):
    """A reference photo used for swapping. Either the camera capture itself, or an uploaded
    photo that matched the camera face."""
    __tablename__ = "face_photos"
    __table_args__ = (
        CheckConstraint("source in ('camera','upload')", name="photo_source"),
        CheckConstraint(
            "source = 'camera' or (match_score is not null and match_score >= match_threshold)",
            name="upload_must_match_camera_face",
        ),
        CheckConstraint("safety_status = 'passed'", name="photo_safety_passed"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    face_id: Mapped[str] = mapped_column(ForeignKey("faces.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    image_key: Mapped[str] = mapped_column(String(512), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)
    match_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    safety_status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    face: Mapped[Face] = relationship(back_populates="photos")


class LivenessChallenge(Base):
    __tablename__ = "liveness_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SourceVideo(Timestamped, Base):
    __tablename__ = "source_videos"
    __table_args__ = (
        CheckConstraint("kind in ('template','upload')", name="video_kind"),
        CheckConstraint("rights_confirmed", name="video_rights_confirmed"),
        CheckConstraint("bytes > 0", name="video_bytes_positive"),
        CheckConstraint("analysis_status in ('pending','analyzing','done','failed')", name="video_analysis_status"),
        CheckConstraint("safety_status in ('pending','passed','blocked')", name="video_safety_status"),
        Index("ix_source_videos_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="upload", nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    video_key: Mapped[str] = mapped_column(String(512), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Numeric(7, 2))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    rights_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rights_note: Mapped[str | None] = mapped_column(Text)
    detected_faces: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    analysis_error: Mapped[str | None] = mapped_column(Text)
    safety_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    safety_result: Mapped[dict | None] = mapped_column(JSON)

    template: Mapped["Template | None"] = relationship(back_populates="video", uselist=False, cascade="all, delete-orphan")


class Template(Timestamped, Base):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id", ondelete="CASCADE"), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    license_note: Mapped[str] = mapped_column(Text, nullable=False)

    video: Mapped[SourceVideo] = relationship(back_populates="template")


class SwapJob(Timestamped, Base):
    __tablename__ = "swap_jobs"
    __table_args__ = (
        CheckConstraint("aspect in ('9:16','16:9')", name="job_aspect"),
        CheckConstraint("target_face_index >= 0", name="job_target_index"),
        CheckConstraint("safety_status in ('pending','passed','blocked')", name="job_safety_status"),
        CheckConstraint(
            "status in ('queued','submitted','processing','postprocessing','done','failed','blocked','cancelled')",
            name="job_status",
        ),
        CheckConstraint(
            "status in ('queued','failed','blocked','cancelled') or safety_status = 'passed'",
            name="safety_before_submit",
        ),
        CheckConstraint(
            "status in ('queued','done','failed','blocked','cancelled') or face_photo_id is not null",
            name="face_required_to_run",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="job_idempotency"),
        UniqueConstraint("provider", "provider_task_id", name="job_provider_task"),
        Index("ix_swap_jobs_status_poll", "status", "next_poll_at"),
        Index("ix_swap_jobs_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_video_id: Mapped[str] = mapped_column(ForeignKey("source_videos.id", ondelete="CASCADE"), nullable=False, index=True)
    face_photo_id: Mapped[str | None] = mapped_column(ForeignKey("face_photos.id", ondelete="SET NULL"), index=True)
    target_face_index: Mapped[int] = mapped_column(Integer, nullable=False)
    aspect: Mapped[str] = mapped_column(String(8), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_task_id: Mapped[str | None] = mapped_column(String(128))
    safety_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    estimated_seconds: Mapped[float | None] = mapped_column(Numeric(7, 2))
    estimated_cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped[SourceVideo] = relationship()
    output: Mapped["Output | None"] = relationship(back_populates="job", uselist=False, cascade="all, delete-orphan")


class Output(Timestamped, Base):
    __tablename__ = "outputs"
    __table_args__ = (
        CheckConstraint("aspect in ('9:16','16:9')", name="output_aspect"),
        CheckConstraint("height >= 720", name="output_hd"),
        CheckConstraint("watermarked", name="output_watermarked"),
        CheckConstraint("c2pa_signed", name="output_c2pa_signed"),
        Index("ix_outputs_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("swap_jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    video_key: Mapped[str] = mapped_column(String(512), nullable=False)
    aspect: Mapped[str] = mapped_column(String(8), nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    watermarked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    c2pa_signed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    job: Mapped[SwapJob] = relationship(back_populates="output")


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint("service in ('faceswap','claude','storage')", name="usage_service"),
        CheckConstraint("cost_micro_usd >= 0", name="usage_cost_positive"),
        Index("ix_usage_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("swap_jobs.id", ondelete="SET NULL"), index=True)
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    units: Mapped[float] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Purge(Base):
    """Files to delete from storage (face photos after a face is deleted, etc.)."""
    __tablename__ = "purges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def make_session_factory(database_url: str):
    url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("pragma foreign_keys=on")
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
