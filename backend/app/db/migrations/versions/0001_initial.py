"""Initial schema with pgvector

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "members",
        sa.Column("member_id", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("date_of_birth", sa.Date, nullable=False),
        sa.Column("gender", sa.String(1), nullable=False),
        sa.Column("relationship", sa.String(20), nullable=False),
        sa.Column("join_date", sa.Date, nullable=False),
        sa.Column("primary_member_id", sa.String(20)),
    )

    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", sa.String(50), nullable=False),
        sa.Column("policy_id", sa.String(50), nullable=False),
        sa.Column("claim_category", sa.String(50), nullable=False),
        sa.Column("treatment_date", sa.Date, nullable=False),
        sa.Column("claimed_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("hospital_name", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("decision", sa.String(20)),
        sa.Column("approved_amount", sa.Numeric(10, 2)),
        sa.Column("confidence_score", sa.Float),
        sa.Column("rejection_reasons", postgresql.JSONB),
        sa.Column("trace", postgresql.JSONB),
        sa.Column("pipeline_errors", postgresql.JSONB),
        sa.Column("simulate_component_failure", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_claims_member_id", "claims", ["member_id"])
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_created_at", "claims", ["created_at"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("file_id", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(255)),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("quality", sa.String(20), server_default="GOOD"),
        sa.Column("content", postgresql.JSONB),
        sa.Column("extracted_data", postgresql.JSONB),
        sa.Column("diagnosis_embedding", sa.String),  # placeholder, altered below
        sa.Column("processing_status", sa.String(20), server_default="PENDING"),
        sa.Column("extraction_confidence", sa.Float),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )

    # Replace placeholder with actual vector type
    op.execute("ALTER TABLE documents DROP COLUMN diagnosis_embedding")
    op.execute("ALTER TABLE documents ADD COLUMN diagnosis_embedding vector(384)")

    op.create_index("ix_documents_claim_id", "documents", ["claim_id"])

    op.create_table(
        "claim_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("member_id", sa.String(50), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True)),
        sa.Column("treatment_date", sa.Date, nullable=False),
        sa.Column("claimed_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("provider", sa.String(200)),
        sa.Column("decision", sa.String(20)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_claim_history_member_id", "claim_history", ["member_id"])
    op.create_index("ix_claim_history_treatment_date", "claim_history", ["treatment_date"])


def downgrade() -> None:
    op.drop_table("claim_history")
    op.drop_table("documents")
    op.drop_table("claims")
    op.drop_table("members")
    op.execute("DROP EXTENSION IF EXISTS vector")
