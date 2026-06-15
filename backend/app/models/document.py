import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, ForeignKey, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.session import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quality: Mapped[Optional[str]] = mapped_column(String(20), default="GOOD")
    content: Mapped[Optional[dict]] = mapped_column(JSONB)
    extracted_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    diagnosis_embedding: Mapped[Optional[list]] = mapped_column(Vector(384))
    processing_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )
