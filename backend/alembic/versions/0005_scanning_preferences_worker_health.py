"""Document scanning, notification preferences, and worker health."""

import sqlalchemy as sa

from alembic import op

revision = "0005_scan_worker_health"
down_revision = "0004_documents_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for _name, column in (
        ("scan_status", sa.Column("scan_status", sa.String(24), nullable=False, server_default="clean")),
        ("scan_engine", sa.Column("scan_engine", sa.String(64))),
        ("scanned_at", sa.Column("scanned_at", sa.DateTime(timezone=True))),
        ("scan_details", sa.Column("scan_details", sa.JSON(), nullable=False, server_default="{}")),
    ):
        op.add_column("curriculum_documents", column)
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.Column("content_release_enabled", sa.Boolean(), nullable=False),
        sa.Column("feedback_enabled", sa.Boolean(), nullable=False),
        sa.Column("digest_frequency", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_name", sa.String(64), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("max_release_lag_seconds", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
    op.drop_table("notification_preferences")
    for name in ("scan_details", "scanned_at", "scan_engine", "scan_status"):
        op.drop_column("curriculum_documents", name)
