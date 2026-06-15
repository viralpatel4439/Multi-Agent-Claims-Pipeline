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
    run_full_pipeline.apply_async(args=[claim_id, claim_data])


@celery_app.task(bind=True, name="tasks.run_full_pipeline", max_retries=0)
def run_full_pipeline(self, claim_id: str, claim_data: dict):
    """
    Monolithic pipeline task — runs all agents sequentially with graceful failure handling.
    """
    import redis as sync_redis

    # Redis NX lock — prevents two workers from running the pipeline for the same claim.
    # TTL is 10 minutes; the lock is released in the finally block on normal completion.
    _redis = sync_redis.from_url(
        __import__("os").environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    lock_key = f"pipeline_lock:{claim_id}"
    acquired = _redis.set(lock_key, "1", nx=True, ex=660)
    if not acquired:
        return {"skipped": True, "reason": f"Pipeline already running for claim {claim_id}"}

    try:
        return _run_pipeline(claim_id, claim_data)
    finally:
        _redis.delete(lock_key)


def _run_pipeline(claim_id: str, claim_data: dict):
    """Inner pipeline — called only after the NX lock is acquired."""
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

    # Step 1: Document extraction — all docs in ONE Ollama call
    extractor = DocumentExtractionAgent()
    extraction_results = []
    extracted_docs: list[ExtractedDocument] = []

    docs_data = claim_data.get("documents", [])
    if simulate_failure and docs_data:
        # For TC011: run first doc via single-run with simulate_failure, rest via batch
        first = DocumentInput(**docs_data[0])
        first_result = run_async(extractor.run(first, simulate_failure=True))
        extraction_results.append(first_result)
        if not first_result.success:
            failed_agents.append(f"DocumentExtractionAgent[{docs_data[0].get('file_id', 0)}]")
        rest = [DocumentInput(**d) for d in docs_data[1:]]
        if rest:
            rest_results = run_async(extractor.run_batch(rest))
            for j, result in enumerate(rest_results):
                extraction_results.append(result)
                if result.success and result.data:
                    try:
                        extracted_docs.append(ExtractedDocument(**result.data))
                    except Exception:
                        pass
                else:
                    failed_agents.append(f"DocumentExtractionAgent[{docs_data[j+1].get('file_id', j+1)}]")
    else:
        doc_inputs = [DocumentInput(**d) for d in docs_data]
        batch_results = run_async(extractor.run_batch(doc_inputs))
        for i, result in enumerate(batch_results):
            extraction_results.append(result)
            if result.success and result.data:
                try:
                    extracted_docs.append(ExtractedDocument(**result.data))
                except Exception:
                    pass
            else:
                failed_agents.append(f"DocumentExtractionAgent[{docs_data[i].get('file_id', i)}]")

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
        # Delete the Redis key so the next poll reads full data from DB.
        # Redis only holds in-flight states (PENDING / PROCESSING).
        await redis_service.delete_claim_status(claim_id)
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
        await redis_service.delete_claim_status(claim_id)
    except Exception:
        pass
