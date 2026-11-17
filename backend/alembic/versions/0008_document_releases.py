"""Cohort-scoped curriculum document releases."""

import sqlalchemy as sa

from alembic import op

revision = "0008_document_releases"
down_revision = "0007_document_release_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curriculum_document_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("released_by_id", sa.Integer(), nullable=False),
        sa.Column("trigger_lesson_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["released_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trigger_lesson_id"], ["lessons.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("cohort_id", "document_id"),
    )
    op.create_index(
        "ix_curriculum_document_releases_visibility",
        "curriculum_document_releases",
        ["cohort_id", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_curriculum_document_releases_visibility", table_name="curriculum_document_releases")
    op.drop_table("curriculum_document_releases")
