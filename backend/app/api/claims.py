import asyncio
import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.document_verifier import DocumentVerificationAgent
from app.config import get_settings
from app.db.session import get_db, AsyncSessionLocal
from app.models.claim import Claim
from app.pipeline.orchestrator import process_claim
from app.schemas.claim import ClaimSubmissionRequest, ClaimResponse, ClaimListItem
from app.services import redis_service
from app.services.policy_service import load_policy

router = APIRouter()
settings = get_settings()

# Maximum tasks allowed to queue before returning 429.
# Keeps clients from piling up work faster than workers can drain it.
_MAX_QUEUE_DEPTH = 500


def _claim_to_response(claim: Claim) -> dict:
    documents = []
    for doc in (claim.raw_submission or {}).get("documents", []):
        file_url = None
        if doc.get("file_path"):
            filename = Path(doc["file_path"]).name
            file_url = f"/api/files/{filename}"
        documents.append({
            "file_id": doc.get("file_id"),
            "file_name": doc.get("file_name"),
            "actual_type": doc.get("actual_type"),
            "quality": doc.get("quality"),
            "file_url": file_url,
        })

    return {
        "claim_id": str(claim.id),
        "member_id": claim.member_id,
        "policy_id": claim.policy_id,
        "claim_category": claim.claim_category,
        "treatment_date": str(claim.treatment_date),
        "claimed_amount": float(claim.claimed_amount),
        "hospital_name": claim.hospital_name,
        "status": claim.status,
        "decision": claim.decision,
        "approved_amount": float(claim.approved_amount) if claim.approved_amount else None,
        "confidence_score": claim.confidence_score,
        "rejection_reasons": claim.rejection_reasons,
        "trace": claim.trace,
        "pipeline_errors": claim.pipeline_errors,
        "documents": documents,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
    }


@router.post("/claims", status_code=202)
async def submit_claim(
    request: ClaimSubmissionRequest,
    db: AsyncSession = Depends(get_db),
):
    policy = load_policy(settings.policy_file_path)

    # Backpressure — reject new submissions when the worker queue is saturated.
    queue_depth = await redis_service.get_queue_depth("pipeline")
    if queue_depth > _MAX_QUEUE_DEPTH:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "QUEUE_SATURATED",
                "queue_depth": queue_depth,
                "message": f"System is processing {queue_depth} claims. Please retry in a few minutes.",
            },
        )

    # Document verification is SYNCHRONOUS — catches bad docs before enqueuing.
    verifier = DocumentVerificationAgent(policy)
    verification_result = await verifier.run(
        documents=request.documents,
        claim_category=request.claim_category,
        member_id=request.member_id,
    )

    if not verification_result.success or not verification_result.data.get("valid"):
        issues = verification_result.data.get("issues", []) if verification_result.data else []
        if not issues and verification_result.error:
            issues = [{"issue_type": "SYSTEM_ERROR", "file_id": None, "message": verification_result.error}]
        raise HTTPException(
            status_code=422,
            detail={
                "error": "DOCUMENT_VALIDATION_FAILED",
                "issues": issues,
                "message": "Document validation failed. Please review the issues and resubmit.",
            },
        )

    # Idempotency guard — return the existing claim if same details are already in flight or done.
    dup_result = await db.execute(
        select(Claim)
        .where(
            Claim.member_id == request.member_id,
            Claim.treatment_date == request.treatment_date,
            Claim.claim_category == request.claim_category,
            Claim.claimed_amount == Decimal(str(request.claimed_amount)),
            Claim.status.in_(["PENDING", "PROCESSING", "COMPLETED"]),
        )
        .order_by(desc(Claim.created_at))
        .limit(1)
    )
    existing = dup_result.scalar_one_or_none()
    if existing:
        return {
            "claim_id": str(existing.id),
            "status": existing.status,
            "duplicate": True,
            "message": "An identical claim is already being processed. Use the claim_id to track its status.",
        }

    claim_data = request.model_dump(mode="json")

    claim = Claim(
        id=uuid.uuid4(),
        member_id=request.member_id,
        policy_id=request.policy_id,
        claim_category=request.claim_category,
        treatment_date=request.treatment_date,
        claimed_amount=request.claimed_amount,
        hospital_name=request.hospital_name,
        status="PENDING",
        simulate_component_failure=request.simulate_component_failure,
        raw_submission=claim_data,
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    claim_id = str(claim.id)

    await redis_service.set_claim_status(claim_id, "PENDING")
    process_claim(claim_id, claim_data)

    return {"claim_id": claim_id, "status": "PENDING"}


@router.get("/claims/{claim_id}/events")
async def claim_events(claim_id: str):
    """
    Server-Sent Events stream for a single claim.
    Sends the current status immediately, then pushes the final result the
    moment the pipeline publishes to Redis pub/sub — no client-side polling needed.
    """
    try:
        uuid.UUID(claim_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid claim ID format.")

    async def generator():
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        ps = r.pubsub()

        try:
            # Subscribe BEFORE checking status to close the race window:
            # if the pipeline completes between our status check and subscribe,
            # we'd otherwise miss the pub/sub message and hang forever.
            await ps.subscribe(f"claim_complete:{claim_id}")

            status_data = await redis_service.get_claim_status(claim_id)

            if not status_data:
                # Claim already completed (or never existed) — serve from DB and close.
                async with AsyncSessionLocal() as session:
                    claim = await session.get(Claim, uuid.UUID(claim_id))
                if claim:
                    yield f"data: {json.dumps(_claim_to_response(claim))}\n\n"
                return

            # Claim is in-flight — send current status so the UI can show a spinner.
            yield f"data: {json.dumps({'claim_id': claim_id, 'status': status_data['status'], 'decision': None})}\n\n"

            # Wait for the pipeline to publish completion (with a hard timeout).
            try:
                async with asyncio.timeout(720):
                    async for message in ps.listen():
                        if message["type"] != "message":
                            continue
                        async with AsyncSessionLocal() as session:
                            claim = await session.get(Claim, uuid.UUID(claim_id))
                        if claim:
                            yield f"data: {json.dumps(_claim_to_response(claim))}\n\n"
                        break
            except asyncio.TimeoutError:
                # Pipeline exceeded hard limit — yield whatever state DB has now.
                async with AsyncSessionLocal() as session:
                    claim = await session.get(Claim, uuid.UUID(claim_id))
                if claim:
                    yield f"data: {json.dumps(_claim_to_response(claim))}\n\n"

        finally:
            await ps.unsubscribe(f"claim_complete:{claim_id}")
            await r.aclose()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx/proxy buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: str,
    db: AsyncSession = Depends(get_db),
):
    status_data = await redis_service.get_claim_status(claim_id)
    if status_data:
        return {
            "claim_id": claim_id,
            "status": status_data["status"],
            "decision": None,
        }

    try:
        claim_uuid = uuid.UUID(claim_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid claim ID format.")

    claim = await db.get(Claim, claim_uuid)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    return _claim_to_response(claim)


@router.get("/claims")
async def list_claims(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Claim).order_by(desc(Claim.created_at)).limit(limit).offset(offset)
    )
    claims = result.scalars().all()
    return [_claim_to_response(c) for c in claims]


@router.post("/claims/{claim_id}/rerun", status_code=202)
async def rerun_claim(
    claim_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        claim_uuid = uuid.UUID(claim_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid claim ID format.")

    claim = await db.get(Claim, claim_uuid)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    if claim.status in ("PENDING", "PROCESSING"):
        raise HTTPException(status_code=409, detail="Pipeline is already running for this claim.")

    if not claim.raw_submission:
        raise HTTPException(status_code=400, detail="No original submission data stored — cannot rerun.")

    claim.status = "PENDING"
    claim.decision = None
    claim.approved_amount = None
    claim.confidence_score = None
    claim.rejection_reasons = None
    claim.trace = None
    claim.pipeline_errors = None
    await db.commit()

    await redis_service.delete_claim_status(claim_id)
    import redis as sync_redis, os
    _r = sync_redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    _r.delete(f"pipeline_lock:{claim_id}")

    await redis_service.set_claim_status(claim_id, "PENDING")
    process_claim(claim_id, claim.raw_submission)

    return {"claim_id": claim_id, "status": "PENDING", "rerun": True}
