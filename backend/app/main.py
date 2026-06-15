from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import claims, members, health, upload, debug
from app.services import embedding_service, redis_service
from app.services.policy_service import load_policy
from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm embedding model and cache policy
    try:
        embedding_service.load_model()
        await redis_service.mark_embedding_model_loaded()
    except Exception as e:
        print(f"Warning: embedding model load failed: {e}")

    try:
        policy = load_policy(settings.policy_file_path)
        print(f"Policy loaded: {policy.policy_id}")
    except Exception as e:
        print(f"Warning: policy load failed: {e}")

    yield

    # Shutdown: nothing to clean up for now


app = FastAPI(
    title="Plum Claims Processing API",
    description="Multi-agent health insurance claims pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(claims.router, prefix="/api", tags=["Claims"])
app.include_router(members.router, prefix="/api", tags=["Members"])
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(debug.router, prefix="/api", tags=["Debug"])


@app.get("/")
async def root():
    return {"message": "Plum Claims API", "docs": "/docs"}
