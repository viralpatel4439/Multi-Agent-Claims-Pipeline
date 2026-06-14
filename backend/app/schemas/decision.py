from typing import Optional
from pydantic import BaseModel


class LineItemDecision(BaseModel):
    description: str
    amount: float
    approved: bool
    approved_amount: float
    reason: Optional[str] = None


class FinancialBreakdown(BaseModel):
    claimed_amount: float
    approved_line_items_total: float
    network_discount_applied: float = 0.0
    amount_after_discount: float
    copay_deducted: float
    final_amount: float
    network_hospital: bool = False


class TraceStep(BaseModel):
    check: str
    passed: bool
    detail: str


class ClaimDecisionOutput(BaseModel):
    claim_id: str
    decision: str
    approved_amount: Optional[float] = None
    confidence_score: float
    rejection_reasons: list[str] = []
    decision_reason: str
    line_item_decisions: list[LineItemDecision] = []
    financial_breakdown: Optional[FinancialBreakdown] = None
    waiting_period_eligible_from: Optional[str] = None
    fraud_signals: list[dict] = []
    trace: dict = {}
    failed_components: list[str] = []
    manual_review_note: Optional[str] = None
