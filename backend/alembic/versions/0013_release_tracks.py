"""squad release tracks (HARBORLINE v0.5)

Revision ID: 0013_release_tracks
Revises: 0012_harborline
Create Date: 2026-11-17 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_release_tracks"
down_revision: str | None = "0012_harborline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("squads", sa.Column("case_track", sa.String(length=8), nullable=True))
    op.add_column("squads", sa.Column("site_team", sa.String(length=8), nullable=True))
    op.add_column("injects", sa.Column("track", sa.String(length=16), nullable=True))
    op.add_column("release_items", sa.Column("track", sa.String(length=16), nullable=True))
    op.add_column("curriculum_document_releases", sa.Column("track", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("curriculum_document_releases", "track")
    op.drop_column("release_items", "track")
    op.drop_column("injects", "track")
    op.drop_column("squads", "site_team")
    op.drop_column("squads", "case_track")
