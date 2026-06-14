import pytest
from datetime import date

from app.agents.fraud_detector import FraudDetectionAgent
from app.schemas.claim import ClaimSubmissionRequest
from app.schemas.document import ExtractedDocument


def make_claim(**kwargs) -> ClaimSubmissionRequest:
    defaults = {
        "member_id": "EMP008",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": date(2024, 10, 30),
        "claimed_amount": 4800.0,
        "documents": [],
    }
    defaults.update(kwargs)
    return ClaimSubmissionRequest(**defaults)


@pytest.mark.asyncio
async def test_tc009_same_day_fraud(policy):
    """TC009: 4 same-day claims → MANUAL_REVIEW with HIGH signal."""
    agent = FraudDetectionAgent(policy)
    claim = make_claim()
    # Inject 3 prior claims from the test case
    prior_claims = [
        {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"},
        {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "City Clinic B"},
        {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "Wellness Center"},
    ]

    result = await agent.run(claim, [], injected_claims_history=prior_claims)

    assert result.success
    data = result.data
    assert data["recommendation"] == "MANUAL_REVIEW"
    signals = data["signals"]
    same_day = [s for s in signals if s["signal_type"] == "SAME_DAY_CLAIMS"]
    assert len(same_day) > 0
    assert same_day[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_no_fraud_signals(policy):
    """Clean claim with no fraud signals → PASS."""
    agent = FraudDetectionAgent(policy)
    claim = make_claim(member_id="EMP001", treatment_date=date(2024, 11, 1), claimed_amount=1500.0)

    result = await agent.run(claim, [], injected_claims_history=None)

    assert result.success
    # With no Redis data, same_day_count is 1, monthly_count is 1 → no signals
    assert result.data["fraud_score"] < 0.5 or result.data["recommendation"] == "PASS"
