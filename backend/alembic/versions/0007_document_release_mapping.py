"""Add audience and release mapping to controlled documents."""

import sqlalchemy as sa

from alembic import op

revision = "0007_document_release_mapping"
down_revision = "0006_async_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("curriculum_documents", sa.Column("audience", sa.String(32)))
    op.add_column("curriculum_documents", sa.Column("release_day", sa.String(16)))
    op.add_column("curriculum_documents", sa.Column("release_block", sa.String(64)))
    op.create_index(
        "ix_curriculum_documents_audience_release_day",
        "curriculum_documents",
        ["audience", "release_day"],
    )


def downgrade() -> None:
    op.drop_index("ix_curriculum_documents_audience_release_day", table_name="curriculum_documents")
    op.drop_column("curriculum_documents", "release_block")
    op.drop_column("curriculum_documents", "release_day")
    op.drop_column("curriculum_documents", "audience")
