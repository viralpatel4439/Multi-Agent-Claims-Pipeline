"""Add raw_submission column to claims

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("raw_submission", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("claims", "raw_submission")
