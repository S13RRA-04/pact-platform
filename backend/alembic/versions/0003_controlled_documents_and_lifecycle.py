"""Controlled curriculum documents and lesson lifecycle."""

import sqlalchemy as sa

from alembic import op

revision = "0003_documents_lifecycle"
down_revision = "0002_lesson_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_releases", sa.Column("state", sa.String(16), nullable=False, server_default="released")
    )
    op.add_column("lesson_releases", sa.Column("scheduled_for", sa.DateTime(timezone=True)))
    op.add_column("lesson_releases", sa.Column("released_at", sa.DateTime(timezone=True)))
    op.add_column("lesson_releases", sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE lesson_releases SET released_at = created_at")
    op.create_check_constraint(
        "ck_lesson_releases_state_valid",
        "lesson_releases",
        "state IN ('scheduled', 'taught', 'released', 'withdrawn')",
    )
    op.create_table(
        "curriculum_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_version_id", sa.Integer(), nullable=False),
        sa.Column("module_id", sa.Integer()),
        sa.Column("document_code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("source_filename", sa.String(256), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("slide_count", sa.Integer()),
        sa.Column("approval_status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_version_id"], ["course_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("course_version_id", "document_code", name="uq_curriculum_document_code"),
        sa.UniqueConstraint("course_version_id", "source_sha256", name="uq_curriculum_document_hash"),
        sa.CheckConstraint(
            "approval_status IN ('draft','pending','approved','rejected','retired')",
            name="ck_curriculum_documents_approval_status_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("curriculum_documents")
    op.drop_constraint("ck_lesson_releases_state_valid", "lesson_releases", type_="check")
    op.drop_column("lesson_releases", "withdrawn_at")
    op.drop_column("lesson_releases", "released_at")
    op.drop_column("lesson_releases", "scheduled_for")
    op.drop_column("lesson_releases", "state")
