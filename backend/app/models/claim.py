import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, Numeric, Boolean, Date, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_id: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(50), nullable=False)
    claim_category: Mapped[str] = mapped_column(String(50), nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hospital_name: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    decision: Mapped[Optional[str]] = mapped_column(String(20))
    approved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    confidence_score: Mapped[Optional[float]]
    rejection_reasons: Mapped[Optional[dict]] = mapped_column(JSONB)
    trace: Mapped[Optional[dict]] = mapped_column(JSONB)
    pipeline_errors: Mapped[Optional[dict]] = mapped_column(JSONB)
    simulate_component_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_submission: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()"), onupdate=datetime.utcnow
    )
