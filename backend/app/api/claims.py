import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.document_verifier import DocumentVerificationAgent
from app.db.session import get_db
from app.models.claim import Claim
from app.pipeline.orchestrator import process_claim
from app.schemas.claim import ClaimSubmissionRequest, ClaimResponse, ClaimListItem
from app.services import redis_service
from app.services.policy_service import load_policy
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def _claim_to_response(claim: Claim) -> dict:
    # Build document list with public file URLs from raw_submission
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

    # Document verification is SYNCHRONOUS — catches TC001/TC002/TC003 immediately
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
    # Checks member_id + treatment_date + claim_category + claimed_amount against PENDING,
    # PROCESSING, and COMPLETED claims. FAILED claims are excluded so the member can resubmit.
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

    # Persist claim as PENDING
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

    # Set Redis status for fast polling
    await redis_service.set_claim_status(claim_id, "PENDING")

    # Enqueue Celery pipeline
    process_claim(claim_id, claim_data)

    return {"claim_id": claim_id, "status": "PENDING"}


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: str,
    db: AsyncSession = Depends(get_db),
):
    # Redis holds the key only while the claim is in flight (PENDING / PROCESSING).
    # The pipeline deletes the key on completion, so a Redis hit always means "still running".
    status_data = await redis_service.get_claim_status(claim_id)
    if status_data:
        return {
            "claim_id": claim_id,
            "status": status_data["status"],
            "decision": None,
        }

    # No Redis key — claim is done (or never existed). Read full data from DB.
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

    # Reset claim state
    claim.status = "PENDING"
    claim.decision = None
    claim.approved_amount = None
    claim.confidence_score = None
    claim.rejection_reasons = None
    claim.trace = None
    claim.pipeline_errors = None
    await db.commit()

    # Clear any stale NX lock from a previous run, then set in-flight status
    await redis_service.delete_claim_status(claim_id)
    _redis_key = f"pipeline_lock:{claim_id}"
    import redis as sync_redis, os
    _r = sync_redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    _r.delete(_redis_key)

    await redis_service.set_claim_status(claim_id, "PENDING")

    process_claim(claim_id, claim.raw_submission)

    return {"claim_id": claim_id, "status": "PENDING", "rerun": True}
