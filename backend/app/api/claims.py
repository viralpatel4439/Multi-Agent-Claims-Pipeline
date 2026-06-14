import uuid
from datetime import datetime
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
    )
    db.add(claim)
    await db.commit()
    await db.refresh(claim)

    claim_id = str(claim.id)

    # Set Redis status for fast polling
    await redis_service.set_claim_status(claim_id, "PENDING")

    # Enqueue Celery pipeline
    claim_data = request.model_dump(mode="json")
    process_claim(claim_id, claim_data)

    return {"claim_id": claim_id, "status": "PENDING"}


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: str,
    db: AsyncSession = Depends(get_db),
):
    # Fast Redis path for in-progress claims
    status_data = await redis_service.get_claim_status(claim_id)
    if status_data and status_data.get("status") in ("PENDING", "PROCESSING"):
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
