from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.services import redis_service, embedding_service

router = APIRouter()


@router.get("/health")
async def health_check():
    status = {"status": "ok", "db": "unknown", "redis": "unknown", "embedding_model": "unknown"}

    # DB check
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        status["db"] = "connected"
    except Exception as e:
        status["db"] = f"error: {str(e)[:100]}"
        status["status"] = "degraded"

    # Redis check
    try:
        ok = await redis_service.ping()
        status["redis"] = "connected" if ok else "error"
        if not ok:
            status["status"] = "degraded"
    except Exception as e:
        status["redis"] = f"error: {str(e)[:100]}"
        status["status"] = "degraded"

    # Embedding model check
    try:
        loaded = await redis_service.is_embedding_model_loaded()
        status["embedding_model"] = "loaded" if loaded else "loading"
    except Exception:
        model = embedding_service._model
        status["embedding_model"] = "loaded" if model is not None else "not_loaded"

    return status
