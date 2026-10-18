"""Baseline the existing CodePilot model schema.

Revision ID: 0001_baseline
Revises:
"""
from alembic import op

from app.database.session import Base
from app import models  # noqa: F401 - registers model metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Creates missing tables/indexes only; does not alter or drop existing data.
    # Existing installs must be schema checked and stamped before upgrading.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Baseline downgrade is intentionally a no-op to preserve user data.
    pass
