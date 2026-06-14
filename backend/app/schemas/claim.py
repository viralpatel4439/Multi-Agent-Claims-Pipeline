import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.document import DocumentInput


class ClaimSubmissionRequest(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: date
    claimed_amount: float
    hospital_name: Optional[str] = None
    documents: list[DocumentInput]
    simulate_component_failure: bool = False
    ytd_claims_amount: Optional[float] = None
    claims_history: Optional[list[dict]] = None


class ClaimResponse(BaseModel):
    claim_id: str
    status: str
    decision: Optional[str] = None
    approved_amount: Optional[float] = None
    confidence_score: Optional[float] = None
    rejection_reasons: Optional[list] = None
    decision_reason: Optional[str] = None
    trace: Optional[dict] = None
    pipeline_errors: Optional[dict] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClaimListItem(BaseModel):
    claim_id: str
    member_id: str
    claim_category: str
    treatment_date: date
    claimed_amount: float
    status: str
    decision: Optional[str] = None
    approved_amount: Optional[float] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
