"""Scalability: HNSW index on diagnosis_embedding, claim_history indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # HNSW index for sub-linear cosine similarity search on diagnosis embeddings.
    # m=16 and ef_construction=64 are standard defaults; tune up for recall vs. speed.
    # CREATE INDEX CONCURRENTLY would be preferable in production to avoid table lock,
    # but Alembic runs in a transaction so we use the plain form here.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_documents_diagnosis_embedding_hnsw
        ON documents
        USING hnsw (diagnosis_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Composite index for fraud counter queries: look up by member + date range
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_claim_history_member_date
        ON claim_history (member_id, treatment_date)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_diagnosis_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_claim_history_member_date")
