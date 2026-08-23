from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(128), nullable=False, unique=True),
    Column("display_name", String(128), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", String(256), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "session_id",
        String(32),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("metadata_json", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "session_id",
        String(32),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_message_id",
        String(32),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("status", String(16), nullable=False),
    Column("question", Text, nullable=False),
    Column("result_text", Text),
    Column(
        "assistant_message_id",
        String(32),
        ForeignKey("messages.id", ondelete="SET NULL"),
    ),
    Column("error", Text),
    Column("error_type", String(256)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('queued', 'running', 'succeeded', 'failed')",
        name="ck_jobs_status",
    ),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("source_artifact_id", String(128), nullable=False),
    Column(
        "job_id",
        String(32),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "message_id",
        String(32),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "session_id",
        String(32),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", Text, nullable=False),
    Column("mime_type", String(128), nullable=False),
    Column("storage_key", Text, nullable=False),
    Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False),
    Column("chart_type", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

job_outbox = Table(
    "job_outbox",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "job_id",
        String(32),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("broker_message_id", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
)

Index("idx_sessions_user_updated", sessions.c.user_id, sessions.c.updated_at.desc())
Index(
    "idx_messages_session_created",
    messages.c.session_id,
    messages.c.user_id,
    messages.c.created_at.desc(),
)
Index("idx_jobs_user_created", jobs.c.user_id, jobs.c.created_at.desc())
Index("idx_jobs_session_status", jobs.c.session_id, jobs.c.status)
Index("idx_artifacts_job", artifacts.c.job_id)
Index(
    "idx_job_outbox_pending",
    job_outbox.c.created_at,
    postgresql_where=job_outbox.c.published_at.is_(None),
    sqlite_where=job_outbox.c.published_at.is_(None),
)
Index(
    "uq_jobs_one_active_per_session",
    jobs.c.session_id,
    unique=True,
    postgresql_where=jobs.c.status.in_(["queued", "running"]),
    sqlite_where=jobs.c.status.in_(["queued", "running"]),
)
