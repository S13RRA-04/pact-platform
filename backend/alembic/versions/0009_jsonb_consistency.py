"""Use JSONB for document/digest JSON columns, matching the rest of the schema and the models.

Migrations 0003, 0005 and 0006 created these as plain JSON while every model maps JSON to JSONB on
PostgreSQL. `alembic check` reported the drift.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_jsonb_consistency"
down_revision = "0008_document_releases"
branch_labels = None
depends_on = None

COLUMNS = (
    ("curriculum_documents", "provenance"),
    ("curriculum_documents", "scan_details"),
    ("notification_digests", "notification_ids"),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=postgresql.JSONB(),
            existing_type=sa.JSON(),
            postgresql_using=f"{column}::jsonb",
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.JSON(),
            existing_type=postgresql.JSONB(),
            postgresql_using=f"{column}::json",
        )
