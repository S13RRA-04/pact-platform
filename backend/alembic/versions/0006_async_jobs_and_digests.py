"""Asynchronous document scans and notification digest outbox."""

import sqlalchemy as sa

from alembic import op

revision = "0006_async_jobs"
down_revision = "0005_scan_worker_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_scan_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_scan_jobs_status", "document_scan_jobs", ["status"])
    op.create_table(
        "notification_digests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("notification_ids", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notification_digests_user_id", "notification_digests", ["user_id"])
    op.create_index("ix_notification_digests_status", "notification_digests", ["status"])


def downgrade() -> None:
    op.drop_table("notification_digests")
    op.drop_table("document_scan_jobs")
