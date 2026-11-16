"""Cohort lesson releases."""

import sqlalchemy as sa

from alembic import op

revision = "0002_lesson_releases"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("released_by_id", sa.Integer(), nullable=False),
        sa.Column("taught_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["released_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("lesson_id", "cohort_id"),
    )


def downgrade() -> None:
    op.drop_table("lesson_releases")
