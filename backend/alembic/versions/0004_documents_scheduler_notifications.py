"""Document versions, protected object keys, and notifications."""

import sqlalchemy as sa

from alembic import op

revision = "0004_documents_jobs"
down_revision = "0003_documents_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_curriculum_document_code", "curriculum_documents", type_="unique")
    op.add_column("curriculum_documents", sa.Column("replaces_document_id", sa.Integer()))
    op.add_column(
        "curriculum_documents", sa.Column("version_number", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("curriculum_documents", sa.Column("object_key", sa.String(512), nullable=True))
    op.execute("UPDATE curriculum_documents SET object_key = 'legacy/' || source_sha256 || '.pptx'")
    op.alter_column("curriculum_documents", "object_key", nullable=False)
    op.create_foreign_key(
        "fk_curriculum_documents_replaces_document_id",
        "curriculum_documents",
        "curriculum_documents",
        ["replaces_document_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_curriculum_document_version",
        "curriculum_documents",
        ["course_version_id", "document_code", "version_number"],
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(48)),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_constraint(
        "fk_curriculum_documents_replaces_document_id", "curriculum_documents", type_="foreignkey"
    )
    op.drop_constraint("uq_curriculum_document_version", "curriculum_documents", type_="unique")
    op.create_unique_constraint(
        "uq_curriculum_document_code", "curriculum_documents", ["course_version_id", "document_code"]
    )
    op.drop_column("curriculum_documents", "object_key")
    op.drop_column("curriculum_documents", "version_number")
    op.drop_column("curriculum_documents", "replaces_document_id")
