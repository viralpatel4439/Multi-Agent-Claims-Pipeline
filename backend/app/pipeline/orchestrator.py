"""
Pipeline orchestrator — enqueues the monolithic Celery task for a claim.

Flow (all inside run_full_pipeline):
  DocumentExtractionAgent (per doc, sequential)
  → PolicyComplianceAgent
  → FraudDetectionAgent
  → DecisionEngine
  → Persist to DB + Redis
"""
import asyncio
from datetime import date as date_type
from typing import Optional

from app.pipeline.celery_app import celery_app


def process_claim(claim_id: str, claim_data: dict) -> None:
    """Enqueue the full pipeline for a submitted claim."""
    run_full_pipeline.apply_async(args=[claim_id, claim_data], queue="default")


@celery_app.task(bind=True, name="tasks.run_full_pipeline", max_retries=0)
def run_full_pipeline(self, claim_id: str, claim_data: dict):
    """
    Monolithic pipeline task — runs all agents sequentially with graceful failure handling.
    """
    def run_async(coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError
            return loop.run_until_complete(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

    from app.agents.document_extractor import DocumentExtractionAgent
    from app.agents.policy_checker import PolicyComplianceAgent
    from app.agents.fraud_detector import FraudDetectionAgent
    from app.agents.decision_engine import DecisionEngine
    from app.schemas.claim import ClaimSubmissionRequest
    from app.schemas.document import DocumentInput, ExtractedDocument
    from app.services.policy_service import load_policy
    from app.config import get_settings
    from app.services import redis_service
    from app.db.session import AsyncSessionLocal
    from app.models.member import Member
    from sqlalchemy import select

    settings = get_settings()
    policy = load_policy(settings.policy_file_path)
    claim = ClaimSubmissionRequest(**claim_data)

    run_async(redis_service.set_claim_status(claim_id, "PROCESSING"))

    failed_agents = []
    simulate_failure = claim_data.get("simulate_component_failure", False)

    # Step 1: Document extraction
    extractor = DocumentExtractionAgent()
    extraction_results = []
    extracted_docs: list[ExtractedDocument] = []

    for i, doc_data in enumerate(claim_data.get("documents", [])):
        doc_input = DocumentInput(**doc_data)
        should_fail = simulate_failure and i == 0
        result = run_async(extractor.run(doc_input, simulate_failure=should_fail))
        extraction_results.append(result)
        if result.success and result.data:
            try:
                extracted_docs.append(ExtractedDocument(**result.data))
            except Exception:
                pass
        else:
            failed_agents.append(f"DocumentExtractionAgent[{doc_data.get('file_id', i)}]")

    # Step 2: Member info from DB
    async def get_member(member_id: str):
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Member).where(Member.member_id == member_id))
                m = res.scalar_one_or_none()
                if m:
                    return m.join_date, m.name
        except Exception:
            pass
        return date_type(2024, 4, 1), "Unknown Member"

    member_join_date, member_name = run_async(get_member(claim.member_id))

    # Step 3: Policy compliance
    compliance_agent = PolicyComplianceAgent(policy)
    compliance_result = run_async(
        compliance_agent.run(claim, extracted_docs, member_join_date, member_name)
    )
    if not compliance_result.success:
        failed_agents.append("PolicyComplianceAgent")

    # Step 4: Fraud detection
    fraud_agent = FraudDetectionAgent(policy)
    fraud_result = run_async(fraud_agent.run(
        claim,
        extracted_docs,
        injected_claims_history=claim_data.get("claims_history"),
    ))
    if not fraud_result.success:
        failed_agents.append("FraudDetectionAgent")

    # Step 5: Decision engine
    engine = DecisionEngine()
    decision_result = run_async(engine.run(
        claim, extraction_results, compliance_result, fraud_result, failed_agents,
    ))

    # Step 6: Persist
    if decision_result.success and decision_result.data:
        run_async(_persist(claim_id, decision_result.data))
    else:
        run_async(_fail(claim_id, decision_result.error or "Decision engine failed"))

    return decision_result.to_dict()


async def _persist(claim_id: str, data: dict):
    from app.db.session import AsyncSessionLocal
    from app.models.claim import Claim
    from app.services import redis_service
    import uuid as _uuid

    try:
        async with AsyncSessionLocal() as session:
            claim = await session.get(Claim, _uuid.UUID(claim_id))
            if claim:
                claim.status = "COMPLETED"
                claim.decision = data.get("decision")
                claim.approved_amount = data.get("approved_amount")
                claim.confidence_score = data.get("confidence_score")
                claim.rejection_reasons = data.get("rejection_reasons", [])
                claim.trace = data.get("trace", {})
                failed = data.get("failed_components", [])
                claim.pipeline_errors = {"failed_components": failed} if failed else None
                await session.commit()
        await redis_service.set_claim_status(claim_id, "COMPLETED", data.get("decision"))
    except Exception:
        pass


async def _fail(claim_id: str, error: str):
    from app.db.session import AsyncSessionLocal
    from app.models.claim import Claim
    from app.services import redis_service
    import uuid as _uuid

    try:
        async with AsyncSessionLocal() as session:
            claim = await session.get(Claim, _uuid.UUID(claim_id))
            if claim:
                claim.status = "FAILED"
                claim.pipeline_errors = {"error": error}
                await session.commit()
        await redis_service.set_claim_status(claim_id, "FAILED")
    except Exception:
        pass
