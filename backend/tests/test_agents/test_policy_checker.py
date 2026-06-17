import pytest
from datetime import date

from app.agents.policy_checker import PolicyComplianceAgent
from app.schemas.claim import ClaimSubmissionRequest
from app.schemas.document import DocumentInput, ExtractedDocument


def make_claim(**kwargs) -> ClaimSubmissionRequest:
    defaults = {
        "member_id": "EMP001",
        "policy_id": "GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": date(2024, 11, 1),
        "claimed_amount": 1500.0,
        "documents": [],
    }
    defaults.update(kwargs)
    return ClaimSubmissionRequest(**defaults)


def make_extracted(diagnosis="Viral Fever", total=1500.0, line_items=None, **kwargs) -> ExtractedDocument:
    return ExtractedDocument(
        document_type="PRESCRIPTION",
        diagnosis=diagnosis,
        total_amount=total,
        line_items=line_items or [{"description": "Consultation Fee", "amount": 1000}, {"description": "CBC Test", "amount": 500}],
        extraction_confidence=0.95,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_tc004_clean_consultation_approved(policy):
    """TC004: Clean consultation → APPROVED at ₹1350 (10% co-pay)."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        treatment_date=date(2024, 11, 1),
        claimed_amount=1500.0,
    )
    docs = [make_extracted(diagnosis="Viral Fever", total=1500.0,
                           line_items=[
                               {"description": "Consultation Fee", "amount": 1000},
                               {"description": "CBC Test", "amount": 300},
                               {"description": "Dengue NS1 Test", "amount": 200},
                           ])]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Rajesh Kumar")

    assert result.success
    assert result.data["decision"] == "APPROVED"
    assert abs(result.data["approved_amount"] - 1350.0) < 0.01


@pytest.mark.asyncio
async def test_tc005_diabetes_waiting_period(policy):
    """TC005: EMP005 claims diabetes treatment within 90-day waiting period → REJECTED."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        member_id="EMP005",
        treatment_date=date(2024, 10, 15),
        claimed_amount=3000.0,
    )
    docs = [make_extracted(
        diagnosis="Type 2 Diabetes Mellitus",
        total=3000.0,
        medicines=["Metformin 500mg", "Glimepiride 1mg"],
    )]

    result = await agent.run(claim, docs, date(2024, 9, 1), "Vikram Joshi")

    assert result.success
    assert result.data["decision"] == "REJECTED"
    assert "WAITING_PERIOD" in result.data["rejection_reasons"]
    assert result.data["waiting_period_eligible_from"] is not None
    # Eligible from 2024-09-01 + 90 days = 2024-11-30
    assert "2024-11-30" in result.data["waiting_period_eligible_from"]


@pytest.mark.asyncio
async def test_tc006_dental_partial_cosmetic(policy):
    """TC006: Root canal (covered) + teeth whitening (excluded) → PARTIAL ₹8000."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        claim_category="DENTAL",
        treatment_date=date(2024, 10, 15),
        claimed_amount=12000.0,
    )
    docs = [ExtractedDocument(
        document_type="HOSPITAL_BILL",
        patient_name="Priya Singh",
        total_amount=12000.0,
        line_items=[
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ],
        extraction_confidence=0.95,
    )]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Priya Singh")

    assert result.success
    assert result.data["decision"] == "PARTIAL"
    assert abs(result.data["approved_amount"] - 8000.0) < 0.01
    # Line items should show teeth whitening rejected
    line_decisions = result.data["line_item_decisions"]
    assert any(not d["approved"] for d in line_decisions)
    assert any(d["approved"] for d in line_decisions)


@pytest.mark.asyncio
async def test_tc007_mri_no_preauth(policy):
    """TC007: MRI ₹15000 without pre-auth → REJECTED."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        claim_category="DIAGNOSTIC",
        treatment_date=date(2024, 11, 2),
        claimed_amount=15000.0,
    )
    docs = [ExtractedDocument(
        document_type="LAB_REPORT",
        diagnosis="Suspected Lumbar Disc Herniation",
        tests_ordered=["MRI Lumbar Spine"],
        total_amount=15000.0,
        line_items=[{"description": "MRI Lumbar Spine", "amount": 15000}],
        extraction_confidence=0.95,
    )]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Suresh Patil")

    assert result.success
    assert result.data["decision"] == "REJECTED"
    assert "PRE_AUTH_MISSING" in result.data["rejection_reasons"]
    # Message should explain how to resubmit
    assert "pre-auth" in result.data["reason_text"].lower() or "authorization" in result.data["reason_text"].lower()


@pytest.mark.asyncio
async def test_tc008_per_claim_limit(policy):
    """TC008: ₹7500 > per-claim limit ₹5000 → REJECTED."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        claimed_amount=7500.0,
        treatment_date=date(2024, 10, 20),
    )
    docs = [make_extracted(diagnosis="Gastroenteritis", total=7500.0,
                           line_items=[
                               {"description": "Consultation Fee", "amount": 2000},
                               {"description": "Medicines", "amount": 5500},
                           ])]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Amit Verma")

    assert result.success
    assert result.data["decision"] == "REJECTED"
    assert "PER_CLAIM_EXCEEDED" in result.data["rejection_reasons"]
    assert "5,000" in result.data["reason_text"] or "5000" in result.data["reason_text"]


@pytest.mark.asyncio
async def test_tc010_network_hospital_discount(policy):
    """TC010: Apollo Hospitals (network) → 20% discount then 10% co-pay = ₹3240."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        member_id="EMP010",
        treatment_date=date(2024, 11, 3),
        claimed_amount=4500.0,
        hospital_name="Apollo Hospitals",
    )
    docs = [ExtractedDocument(
        document_type="HOSPITAL_BILL",
        patient_name="Deepak Shah",
        hospital_name="Apollo Hospitals",
        diagnosis="Acute Bronchitis",
        total_amount=4500.0,
        line_items=[
            {"description": "Consultation Fee", "amount": 1500},
            {"description": "Medicines", "amount": 3000},
        ],
        extraction_confidence=0.95,
    )]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Deepak Shah")

    assert result.success
    assert result.data["decision"] == "APPROVED"
    assert abs(result.data["approved_amount"] - 3240.0) < 0.01

    bd = result.data["financial_breakdown"]
    assert bd["network_hospital"] is True
    assert abs(bd["network_discount_applied"] - 900.0) < 0.01
    assert abs(bd["copay_deducted"] - 360.0) < 0.01


@pytest.mark.asyncio
async def test_tc012_excluded_bariatric(policy):
    """TC012: Bariatric consultation → REJECTED EXCLUDED_CONDITION."""
    agent = PolicyComplianceAgent(policy)
    claim = make_claim(
        member_id="EMP009",
        treatment_date=date(2024, 10, 18),
        claimed_amount=8000.0,
    )
    docs = [ExtractedDocument(
        document_type="PRESCRIPTION",
        diagnosis="Morbid Obesity — BMI 37",
        treatment="Bariatric Consultation and Customised Diet Plan",
        total_amount=8000.0,
        line_items=[
            {"description": "Bariatric Consultation", "amount": 3000},
            {"description": "Personalised Diet and Nutrition Program", "amount": 5000},
        ],
        extraction_confidence=0.95,
    )]

    result = await agent.run(claim, docs, date(2024, 4, 1), "Anita Desai")

    assert result.success
    assert result.data["decision"] == "REJECTED"
    assert "EXCLUDED_CONDITION" in result.data["rejection_reasons"]
    assert result.data["confidence"] >= 0.90
