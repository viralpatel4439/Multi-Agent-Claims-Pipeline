"""
Pipeline orchestrator — enqueues the monolithic Celery task for a claim.

Flow (all inside run_full_pipeline):
  DocumentExtractionAgent (batch Ollama call, all docs at once)
  → PolicyComplianceAgent || FraudDetectionAgent  (asyncio.gather — parallel)
  → DecisionEngine
  → Persist to DB (claim + documents + claim_history) + Redis pub/sub notification
"""
import asyncio
from datetime import date as date_type
from typing import Optional

from app.pipeline.celery_app import celery_app


def process_claim(claim_id: str, claim_data: dict) -> None:
    """Enqueue the full pipeline for a submitted claim."""
    run_full_pipeline.apply_async(args=[claim_id, claim_data], queue="pipeline")


@celery_app.task(
    bind=True,
    name="tasks.run_full_pipeline",
    max_retries=3,
    default_retry_delay=30,
)
def run_full_pipeline(self, claim_id: str, claim_data: dict):
    """
    Monolithic pipeline task — runs agents with graceful failure handling.
    Retries up to 3 times (exponential backoff) on transient infrastructure errors.
    """
    import redis as sync_redis
    import os

    _redis = sync_redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
    lock_key = f"pipeline_lock:{claim_id}"
    # NX lock — prevents two workers running the same claim simultaneously.
    acquired = _redis.set(lock_key, "1", nx=True, ex=720)
    if not acquired:
        return {"skipped": True, "reason": f"Pipeline already running for claim {claim_id}"}

    try:
        return _run_pipeline(claim_id, claim_data)
    except Exception as exc:
        # Retry on transient infrastructure errors; let business-logic exceptions through.
        _transient_names = {"OperationalError", "DisconnectionError", "ConnectionError", "TimeoutError"}
        transient = type(exc).__name__ in _transient_names or isinstance(exc, (ConnectionError, TimeoutError))
        if transient:
            # Release the lock before re-queuing so the retry can acquire it.
            _redis.delete(lock_key)
            countdown = 30 * (3 ** self.request.retries)  # 30s, 90s, 270s
            raise self.retry(exc=exc, countdown=countdown)
        raise
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

    # ── Step 1: Document extraction — all docs in ONE Ollama call ──────────────
    extractor = DocumentExtractionAgent()
    extraction_results = []
    extracted_docs: list[ExtractedDocument] = []

    docs_data = claim_data.get("documents", [])
    if simulate_failure and docs_data:
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

    # ── Step 2: Member info from DB ────────────────────────────────────────────
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

    # ── Steps 3+4: Policy compliance and fraud detection — run in parallel ─────
    compliance_agent = PolicyComplianceAgent(policy)
    fraud_agent = FraudDetectionAgent(policy)

    async def run_agents_parallel():
        return await asyncio.gather(
            compliance_agent.run(claim, extracted_docs, member_join_date, member_name),
            fraud_agent.run(
                claim,
                extracted_docs,
                injected_claims_history=claim_data.get("claims_history"),
            ),
            return_exceptions=True,
        )

    results = run_async(run_agents_parallel())
    compliance_result, fraud_result = results

    # Handle agent-level exceptions gracefully
    if isinstance(compliance_result, Exception):
        from app.agents.base import AgentResult
        compliance_result = AgentResult(
            success=False, data={}, error=str(compliance_result),
            agent_name="PolicyComplianceAgent",
        )
        failed_agents.append("PolicyComplianceAgent")

    if isinstance(fraud_result, Exception):
        from app.agents.base import AgentResult
        fraud_result = AgentResult(
            success=False, data={}, error=str(fraud_result),
            agent_name="FraudDetectionAgent",
        )
        failed_agents.append("FraudDetectionAgent")

    if not compliance_result.success:
        failed_agents.append("PolicyComplianceAgent")
    if not fraud_result.success:
        failed_agents.append("FraudDetectionAgent")

    # ── Step 5: Decision engine ────────────────────────────────────────────────
    engine = DecisionEngine()
    decision_result = run_async(engine.run(
        claim, extraction_results, compliance_result, fraud_result, failed_agents,
    ))

    # ── Step 6: Persist ────────────────────────────────────────────────────────
    if decision_result.success and decision_result.data:
        run_async(_persist(claim_id, decision_result.data, docs_data, extraction_results, claim))
    else:
        run_async(_fail(claim_id, decision_result.error or "Decision engine failed"))

    return decision_result.to_dict()


async def _persist(
    claim_id: str,
    data: dict,
    docs_data: list = None,
    extraction_results: list = None,
    claim=None,
):
    from app.db.session import AsyncSessionLocal
    from app.models.claim import Claim
    from app.models.document import Document
    from app.models.claim_history import ClaimHistory
    from app.services import redis_service
    import uuid as _uuid

    try:
        async with AsyncSessionLocal() as session:
            claim_row = await session.get(Claim, _uuid.UUID(claim_id))
            if claim_row:
                claim_row.status = "COMPLETED"
                claim_row.decision = data.get("decision")
                claim_row.approved_amount = data.get("approved_amount")
                claim_row.confidence_score = data.get("confidence_score")
                claim_row.rejection_reasons = data.get("rejection_reasons", [])
                claim_row.trace = data.get("trace", {})
                failed = data.get("failed_components", [])
                claim_row.pipeline_errors = {"failed_components": failed} if failed else None

            # Persist each extracted document with its embedding
            for i, result in enumerate(extraction_results or []):
                doc_meta = (docs_data or [])[i] if i < len(docs_data or []) else {}
                extracted = result.data or {}
                embedding = extracted.get("diagnosis_embedding")
                doc_row = Document(
                    claim_id=_uuid.UUID(claim_id),
                    file_id=doc_meta.get("file_id", str(i)),
                    file_name=doc_meta.get("file_name"),
                    document_type=extracted.get("document_type") or doc_meta.get("actual_type", "unknown"),
                    quality=doc_meta.get("quality", "GOOD"),
                    content=doc_meta.get("content"),
                    extracted_data={k: v for k, v in extracted.items() if k != "diagnosis_embedding"},
                    diagnosis_embedding=embedding,
                    processing_status="COMPLETED" if result.success else "FAILED",
                    extraction_confidence=extracted.get("extraction_confidence"),
                )
                session.add(doc_row)

            # Write to claim_history so fraud detection has durable historical data
            if claim is not None:
                from datetime import date as _date
                member_id = claim.member_id if hasattr(claim, "member_id") else None
                treatment_date = claim.treatment_date if hasattr(claim, "treatment_date") else _date.today()
                claimed_amount = claim.claimed_amount if hasattr(claim, "claimed_amount") else 0
                hospital_name = claim.hospital_name if hasattr(claim, "hospital_name") else None

                history_row = ClaimHistory(
                    member_id=member_id,
                    claim_id=_uuid.UUID(claim_id),
                    treatment_date=treatment_date,
                    claimed_amount=claimed_amount,
                    provider=hospital_name,
                    decision=data.get("decision"),
                )
                session.add(history_row)

            await session.commit()

        # Notify SSE subscribers that this claim is done
        await redis_service.publish_claim_complete(claim_id)
        # Delete the Redis in-flight key — next poll reads full data from DB
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
        await redis_service.publish_claim_complete(claim_id)
        await redis_service.delete_claim_status(claim_id)
    except Exception:
        pass
