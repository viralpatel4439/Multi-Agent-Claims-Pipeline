"""
GET /api/tests/run — runs all 12 test cases through the agent pipeline in-process
and returns structured pass/fail results.

No Celery, no DB, no Ollama — uses structured content extraction exactly as the
pytest suite does, so results are available in ~200 ms.
"""
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from app.agents.decision_engine import DecisionEngine
from app.agents.document_extractor import DocumentExtractionAgent
from app.agents.document_verifier import DocumentVerificationAgent
from app.agents.fraud_detector import FraudDetectionAgent
from app.agents.policy_checker import PolicyComplianceAgent
from app.config import get_settings
from app.schemas.claim import ClaimSubmissionRequest
from app.schemas.document import DocumentInput, ExtractedDocument
from app.services.policy_service import load_policy

router = APIRouter()
settings = get_settings()

# Mounted at /app/test_cases.json via docker-compose volume.
TEST_CASES_FILE = Path("/app/test_cases.json")

_JOIN_DATES: dict[str, date] = {
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

_NAMES: dict[str, str] = {
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


async def _run_case(case: dict, policy) -> dict:
    case_id: str = case["case_id"]
    description: str = case.get("description", "")
    expected: dict = case["expected"]
    inp: dict = case["input"]
    t0 = time.monotonic()

    try:
        claim = ClaimSubmissionRequest(
            member_id=inp["member_id"],
            policy_id=inp["policy_id"],
            claim_category=inp["claim_category"],
            treatment_date=date.fromisoformat(inp["treatment_date"]),
            claimed_amount=float(inp["claimed_amount"]),
            hospital_name=inp.get("hospital_name"),
            documents=[DocumentInput(**d) for d in inp.get("documents", [])],
            simulate_component_failure=inp.get("simulate_component_failure", False),
            claims_history=inp.get("claims_history"),
        )

        member_id = inp["member_id"]
        join_date = _JOIN_DATES.get(member_id, date(2024, 4, 1))
        member_name = _NAMES.get(member_id, "Unknown")
        simulate_failure = inp.get("simulate_component_failure", False)

        # ── Step 1: Document Verification ──────────────────────────────────────
        verifier = DocumentVerificationAgent(policy)
        docs = [DocumentInput(**d) for d in inp.get("documents", [])]
        verification = await verifier.run(docs, inp["claim_category"], member_id)

        if not verification.data.get("valid"):
            issues = verification.data.get("issues", [])
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            expected_decision = expected.get("decision")

            if expected_decision is None:
                passed = True
                failure_reason = None
            else:
                passed = False
                failure_reason = (
                    f"Expected decision={expected_decision} but verification failed: "
                    + "; ".join(i["message"] for i in issues)
                )

            return _result(
                case_id, description, passed, failure_reason,
                expected_decision=expected_decision,
                actual_decision=None,
                expected_amount=expected.get("approved_amount"),
                actual_amount=None,
                actual_confidence=None,
                rejection_reasons=[],
                failed_components=[],
                waiting_period_eligible_from=None,
                issues=issues,
                decision_reason=None,
                elapsed_ms=elapsed_ms,
            )

        # ── Step 2: Extraction (content-based, no LLM) ─────────────────────────
        extractor = DocumentExtractionAgent()
        extractor.client = None  # force structured-content path

        extraction_results = []
        final_extracted: list[ExtractedDocument] = []
        for i, doc_data in enumerate(inp.get("documents", [])):
            doc_input = DocumentInput(**doc_data)
            should_fail = simulate_failure and i == 0
            result = await extractor.run(doc_input, simulate_failure=should_fail)
            extraction_results.append(result)
            if result.success and result.data:
                try:
                    final_extracted.append(ExtractedDocument(**result.data))
                except Exception:
                    pass

        # ── Step 3: Policy Compliance ──────────────────────────────────────────
        compliance_agent = PolicyComplianceAgent(policy)
        compliance_result = await compliance_agent.run(
            claim, final_extracted, join_date, member_name
        )

        # ── Step 4: Fraud Detection ────────────────────────────────────────────
        fraud_agent = FraudDetectionAgent(policy)
        fraud_result = await fraud_agent.run(
            claim,
            final_extracted,
            injected_claims_history=inp.get("claims_history"),
        )

        # ── Step 5: Decision Engine ────────────────────────────────────────────
        failed_agents = [r.agent_name for r in extraction_results if not r.success]
        engine = DecisionEngine()
        decision_result = await engine.run(
            claim, extraction_results, compliance_result, fraud_result, failed_agents
        )
        decision = decision_result.data
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # ── Assert ─────────────────────────────────────────────────────────────
        passed = True
        failure_reason: Optional[str] = None

        if decision["decision"] != expected["decision"]:
            passed = False
            failure_reason = (
                f"Expected {expected['decision']} but got {decision['decision']}. "
                f"Reason: {decision.get('decision_reason', '')}"
            )
        elif "approved_amount" in expected:
            diff = abs((decision.get("approved_amount") or 0) - expected["approved_amount"])
            if diff >= 1.0:
                passed = False
                failure_reason = (
                    f"Amount mismatch: expected ₹{expected['approved_amount']}, "
                    f"got ₹{decision.get('approved_amount')}"
                )

        return _result(
            case_id, description, passed, failure_reason,
            expected_decision=expected.get("decision"),
            actual_decision=decision["decision"],
            expected_amount=expected.get("approved_amount"),
            actual_amount=decision.get("approved_amount"),
            actual_confidence=decision.get("confidence_score"),
            rejection_reasons=decision.get("rejection_reasons", []),
            failed_components=decision.get("failed_components", []),
            waiting_period_eligible_from=decision.get("waiting_period_eligible_from"),
            issues=[],
            decision_reason=decision.get("decision_reason"),
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:
        return _result(
            case_id, description, False, str(exc),
            expected_decision=expected.get("decision"),
            actual_decision=None,
            expected_amount=expected.get("approved_amount"),
            actual_amount=None,
            actual_confidence=None,
            rejection_reasons=[],
            failed_components=[],
            waiting_period_eligible_from=None,
            issues=[],
            decision_reason=None,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            status="ERROR",
        )


def _result(
    case_id, description, passed, failure_reason, *,
    expected_decision, actual_decision,
    expected_amount, actual_amount, actual_confidence,
    rejection_reasons, failed_components, waiting_period_eligible_from,
    issues, decision_reason, elapsed_ms, status: Optional[str] = None,
) -> dict:
    if status is None:
        status = "PASSED" if passed else "FAILED"
    return {
        "case_id": case_id,
        "description": description,
        "status": status,
        "failure_reason": failure_reason,
        "expected_decision": expected_decision,
        "actual_decision": actual_decision,
        "expected_amount": expected_amount,
        "actual_amount": actual_amount,
        "actual_confidence": actual_confidence,
        "rejection_reasons": rejection_reasons,
        "failed_components": failed_components,
        "waiting_period_eligible_from": waiting_period_eligible_from,
        "issues": issues,
        "decision_reason": decision_reason,
        "duration_ms": elapsed_ms,
    }


@router.get("/tests/run")
async def run_test_suite():
    """Run all 12 test cases through the agent pipeline and return structured results."""
    if not TEST_CASES_FILE.exists():
        return {
            "error": (
                f"test_cases.json not found at {TEST_CASES_FILE}. "
                "Add '- ./test_cases.json:/app/test_cases.json:ro' to the backend "
                "volumes in docker-compose.yml and rebuild."
            )
        }

    with open(TEST_CASES_FILE) as f:
        test_cases = json.load(f)["test_cases"]

    policy = load_policy(settings.policy_file_path)
    t0 = time.monotonic()

    results = []
    for case in test_cases:
        results.append(await _run_case(case, policy))

    total_ms = int((time.monotonic() - t0) * 1000)
    passed = sum(1 for r in results if r["status"] == "PASSED")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    errored = sum(1 for r in results if r["status"] == "ERROR")

    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "duration_ms": total_ms,
        "results": results,
    }
