"""
Integration test: run all 12 test cases through the agent pipeline.
These tests exercise the agents directly (not through HTTP or Celery)
so they run without any external services.

Each test asserts the decision and key fields match the expected output from test_cases.json.
"""
import json
import pytest
from datetime import date, datetime
from pathlib import Path

from app.agents.document_verifier import DocumentVerificationAgent
from app.agents.document_extractor import DocumentExtractionAgent
from app.agents.policy_checker import PolicyComplianceAgent
from app.agents.fraud_detector import FraudDetectionAgent
from app.agents.decision_engine import DecisionEngine
from app.schemas.claim import ClaimSubmissionRequest
from app.schemas.document import DocumentInput, ExtractedDocument

# Resolve test_cases.json path: Docker mounts it at /app/test_cases.json;
# locally it lives four directories up from this file (at the repo root).
_DOCKER_PATH = Path("/app/test_cases.json")
_LOCAL_PATH = Path(__file__).parent.parent.parent.parent / "test_cases.json"
TEST_CASES_FILE = _DOCKER_PATH if _DOCKER_PATH.exists() else _LOCAL_PATH

MEMBER_JOIN_DATES = {
    "EMP001": date(2024, 4, 1),
    "EMP002": date(2024, 4, 1),
    "EMP003": date(2024, 4, 1),
    "EMP004": date(2024, 4, 1),
    "EMP005": date(2024, 9, 1),
    "EMP006": date(2024, 4, 1),
    "EMP007": date(2024, 4, 1),
    "EMP008": date(2024, 4, 1),
    "EMP009": date(2024, 4, 1),
    "EMP010": date(2024, 4, 1),
}

MEMBER_NAMES = {
    "EMP001": "Rajesh Kumar",
    "EMP002": "Priya Singh",
    "EMP003": "Amit Verma",
    "EMP004": "Sneha Reddy",
    "EMP005": "Vikram Joshi",
    "EMP006": "Kavita Nair",
    "EMP007": "Suresh Patil",
    "EMP008": "Ravi Menon",
    "EMP009": "Anita Desai",
    "EMP010": "Deepak Shah",
}


def load_test_cases():
    with open(TEST_CASES_FILE) as f:
        return json.load(f)["test_cases"]


def build_claim(case_input: dict) -> ClaimSubmissionRequest:
    return ClaimSubmissionRequest(
        member_id=case_input["member_id"],
        policy_id=case_input["policy_id"],
        claim_category=case_input["claim_category"],
        treatment_date=date.fromisoformat(case_input["treatment_date"]),
        claimed_amount=float(case_input["claimed_amount"]),
        hospital_name=case_input.get("hospital_name"),
        documents=[DocumentInput(**d) for d in case_input["documents"]],
        simulate_component_failure=case_input.get("simulate_component_failure", False),
        claims_history=case_input.get("claims_history"),
    )


def build_extracted_docs(documents: list) -> list[ExtractedDocument]:
    """Build ExtractedDocument from the content fields in the test case."""
    result = []
    for doc in documents:
        content = doc.get("content") or {}
        line_items = [
            {"description": item.get("description", ""), "amount": float(item.get("amount", 0))}
            for item in content.get("line_items", [])
        ]
        extracted = ExtractedDocument(
            document_type=doc.get("actual_type", "UNKNOWN"),
            patient_name=content.get("patient_name"),
            doctor_name=content.get("doctor_name"),
            doctor_registration=content.get("doctor_registration"),
            diagnosis=content.get("diagnosis"),
            treatment=content.get("treatment"),
            hospital_name=content.get("hospital_name"),
            medicines=content.get("medicines", []),
            tests_ordered=content.get("tests_ordered", []),
            line_items=line_items,
            total_amount=content.get("total"),
            extraction_confidence=0.95 if content else 0.0,
        )
        result.append(extracted)
    return result


async def run_pipeline(case: dict, policy):
    """Run the full agent pipeline for a test case. Returns (verification_result, decision)."""
    inp = case["input"]
    claim = build_claim(inp)
    extracted_docs = build_extracted_docs(inp.get("documents", []))
    member_id = inp["member_id"]
    join_date = MEMBER_JOIN_DATES.get(member_id, date(2024, 4, 1))
    member_name = MEMBER_NAMES.get(member_id, "Unknown")
    simulate_failure = inp.get("simulate_component_failure", False)

    # Step 1: Verification
    verifier = DocumentVerificationAgent(policy)
    docs = [DocumentInput(**d) for d in inp.get("documents", [])]
    verification = await verifier.run(docs, inp["claim_category"], member_id)

    if not verification.data.get("valid"):
        return verification, None

    # Step 2: Extraction (disable LLM, use direct content extraction)
    extractor = DocumentExtractionAgent()
    extractor.client = None  # force non-LLM fallback

    extraction_results = []
    final_extracted_docs = []
    for i, doc_data in enumerate(inp.get("documents", [])):
        doc_input = DocumentInput(**doc_data)
        should_fail = simulate_failure and i == 0
        result = await extractor.run(doc_input, simulate_failure=should_fail)
        extraction_results.append(result)
        if result.success and result.data:
            try:
                final_extracted_docs.append(ExtractedDocument(**result.data))
            except Exception:
                pass

    # Step 3: Policy compliance
    compliance_agent = PolicyComplianceAgent(policy)
    compliance_result = await compliance_agent.run(claim, final_extracted_docs, join_date, member_name)

    # Step 4: Fraud detection
    fraud_agent = FraudDetectionAgent(policy)
    fraud_result = await fraud_agent.run(
        claim,
        final_extracted_docs,
        injected_claims_history=inp.get("claims_history"),
    )

    # Step 5: Decision engine
    failed_agents = []
    for r in extraction_results:
        if not r.success:
            failed_agents.append(r.agent_name)

    engine = DecisionEngine()
    decision_result = await engine.run(
        claim,
        extraction_results,
        compliance_result,
        fraud_result,
        failed_agents,
    )

    return verification, decision_result.data


# Load test cases at module level for parametrize
_test_cases = load_test_cases() if TEST_CASES_FILE.exists() else []


@pytest.mark.parametrize("case", _test_cases, ids=[c["case_id"] for c in _test_cases])
@pytest.mark.asyncio
async def test_case(case, policy):
    """Run each of the 12 test cases and assert against expected output."""
    verification, decision = await run_pipeline(case, policy)
    expected = case["expected"]
    case_id = case["case_id"]

    if expected.get("decision") is None:
        # TC001, TC002, TC003 — expect validation failure
        assert not verification.data["valid"], (
            f"{case_id}: Expected document validation to FAIL but it PASSED"
        )
        issues = verification.data["issues"]
        assert len(issues) > 0, f"{case_id}: Expected issues but got none"

        # Verify message specificity
        if case_id == "TC001":
            msgs = " ".join(i["message"] for i in issues)
            assert "HOSPITAL_BILL" in msgs, f"TC001: 'HOSPITAL_BILL' not in error message: {msgs}"
            assert "PRESCRIPTION" in msgs, f"TC001: 'PRESCRIPTION' not in error message: {msgs}"

        if case_id == "TC002":
            types = [i["issue_type"] for i in issues]
            assert "UNREADABLE" in types, f"TC002: Expected UNREADABLE issue, got: {types}"

        if case_id == "TC003":
            types = [i["issue_type"] for i in issues]
            assert "PATIENT_MISMATCH" in types, f"TC003: Expected PATIENT_MISMATCH, got: {types}"
            msgs = " ".join(i["message"] for i in issues)
            assert "Rajesh Kumar" in msgs, "TC003: Expected 'Rajesh Kumar' in message"
            assert "Arjun Mehta" in msgs, "TC003: Expected 'Arjun Mehta' in message"

    else:
        # TC004 through TC012 — expect a decision
        assert verification.data["valid"], (
            f"{case_id}: Expected valid docs but got: {verification.data['issues']}"
        )
        assert decision is not None, f"{case_id}: Decision is None"
        assert decision["decision"] == expected["decision"], (
            f"{case_id}: Expected {expected['decision']} but got {decision['decision']}. "
            f"Reason: {decision.get('decision_reason')}"
        )

        # Check approved amount if specified
        if "approved_amount" in expected:
            actual_amount = decision.get("approved_amount", 0)
            expected_amount = expected["approved_amount"]
            assert abs(actual_amount - expected_amount) < 1.0, (
                f"{case_id}: Expected ₹{expected_amount} but got ₹{actual_amount}"
            )

        # Check confidence score if specified
        if "confidence_score" in expected:
            conf = expected["confidence_score"]
            if isinstance(conf, str) and conf.startswith("above"):
                threshold = float(conf.split()[-1])
                assert decision["confidence_score"] >= threshold, (
                    f"{case_id}: Confidence {decision['confidence_score']} < {threshold}"
                )

        # Check rejection reasons
        if "rejection_reasons" in expected:
            for reason in expected["rejection_reasons"]:
                assert reason in decision["rejection_reasons"], (
                    f"{case_id}: Expected reason {reason} not in {decision['rejection_reasons']}"
                )

        # TC011 specific: failed components must be visible
        if case_id == "TC011":
            assert len(decision.get("failed_components", [])) > 0, (
                "TC011: Expected failed_components to be populated"
            )
            assert decision["confidence_score"] < 0.85, (
                "TC011: Confidence should be reduced due to component failure"
            )

        # TC005 specific: eligible date must be visible
        if case_id == "TC005":
            eligible = decision.get("waiting_period_eligible_from")
            assert eligible is not None, "TC005: Expected waiting_period_eligible_from in decision"
            # 2024-09-01 + 90 days = 2024-11-30
            assert "2024-11-30" in eligible, f"TC005: Expected 2024-11-30 in eligible date, got {eligible}"

        print(f"\n✓ {case_id} — {decision['decision']} "
              f"(₹{decision.get('approved_amount', 0):.2f}, "
              f"confidence={decision.get('confidence_score', 0):.2f})")
