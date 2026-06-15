# Execution Guide

## Prerequisites

- Docker Desktop (Mac/Windows/Linux)
- Python 3.12+ (for local test runs only)
- [Ollama](https://github.com/viralpatel4439/Local-Model-Setup) running locally with `qwen2.5vl:3b` pulled (only needed for live vision extraction; tests work without it)

---

## 1. Environment Setup

Copy the example env file:

```bash
cp .env.example .env
```

All values work as-is for local Docker use. If Ollama runs on a non-default host or port, update these two variables:

```
OLLAMA_URL=http://localhost:11434
OLLAMA_VISION_MODEL=qwen2.5vl:3b
```

To run more Celery workers per container (default is 4):

```
CELERY_WORKER_CONCURRENCY=8
```

---

## 2. Run Everything in Docker

```bash
docker-compose up -d
```

This starts: `postgres`, `redis`, `backend` (FastAPI), `celery_worker`, `flower`, `frontend`.

**Migrations run automatically.** The backend entrypoint runs `alembic upgrade head` before uvicorn starts. This applies all three migrations in order:
- `0001_initial` — creates all tables, enables pgvector extension
- `0002_add_raw_submission` — adds `raw_submission` JSONB column to claims
- `0003_scalability` — creates HNSW index on `documents.diagnosis_embedding` and composite index on `claim_history`

Alembic tracks applied migrations in `alembic_version` — subsequent restarts are a no-op for already-applied revisions. The seed uses `ON CONFLICT DO UPDATE` so re-runs never duplicate member data.

Wait for services to be healthy (about 30–60 seconds on first run):

```bash
docker-compose ps
```

All services should show `running` or `healthy`.

---

## 3. Verify the Stack

```bash
curl http://localhost:8000/api/health
```

Expected:

```json
{"status": "ok", "db": "connected", "redis": "connected", "embedding_model": "loaded"}
```

---

## 4. Access the UI

| URL | What it is |
|---|---|
| `http://localhost:3000` | Claim submission form |
| `http://localhost:3000/claims` | All submitted claims list |
| `http://localhost:8000/docs` | FastAPI Swagger UI |
| `http://localhost:5555` | Flower — Celery task monitor |

---

## 5. Manual End-to-End Test (TC004 — APPROVED)

Submit a TC004-equivalent claim through the UI:

1. Open `http://localhost:3000`
2. Select member **EMP001**, category **CONSULTATION**, hospital **Apollo Hospitals** (network)
3. Treatment date: **2024-11-15**, claimed amount: **1500**
4. Add one document — type **PRESCRIPTION**, quality **GOOD**, patient name **Rajesh Kumar**
5. Submit → redirected to `/claims/{id}`
6. The detail page opens an SSE connection and shows a spinner. When Ollama finishes vision extraction (typically 60–120 s depending on GPU), the final result is pushed instantly — no manual refresh needed.
7. Expected: **APPROVED**, approved amount **₹1,350** (10% co-pay on ₹1,500)

> **Note:** If submitting a claim with a JSON content body instead of a real file upload, results arrive in ~1–2 seconds (no Ollama call).

---

## 6. Scale Workers Horizontally

Add more Celery workers without changing any config:

```bash
docker-compose up -d --scale celery_worker=3
```

All three worker containers share the same `pipeline` Redis queue and the same `uploads` volume. Flower at `http://localhost:5555` shows all active workers.

To set concurrency per worker (default 4):

```bash
CELERY_WORKER_CONCURRENCY=8 docker-compose up -d --scale celery_worker=3
```

This gives 3 × 8 = 24 concurrent claim pipelines.

---

## 7. Run Tests Locally (No Docker Needed)

Tests run against a lightweight local Python environment — no torch, no sentence-transformers, no real database or Redis required.

### One-time setup

```bash
cd backend
python3 -m venv .venv-core
source .venv-core/bin/activate
pip install -r requirements-dev.txt
```

### Run all tests

```bash
cd backend
source .venv-core/bin/activate
python -m pytest tests/ -v
```

Expected output:

```
29 passed, 3 warnings in 0.12s
```

The 3 warnings are Pydantic v2 deprecation notices for class-based `Config` — non-blocking.

### Run a specific test file

```bash
python -m pytest tests/test_cases/test_all_12_cases.py -v      # All 12 assignment test cases
python -m pytest tests/test_agents/test_policy_checker.py -v   # Policy logic only
python -m pytest tests/test_agents/test_fraud_detector.py -v   # Fraud detection only
```

---

## 8. Stop Everything

```bash
docker-compose down
```

To also remove the database and Redis volumes (wipes all data):

```bash
docker-compose down -v
```

Wipe all containers, images, and volumes for this project in one command:

```bash
docker-compose down --rmi all --volumes --remove-orphans
```

---

## 9. Rebuild After Code Changes

```bash
docker-compose up -d --build backend celery_worker
```

The frontend only needs a rebuild if you changed frontend code:

```bash
docker-compose up -d --build frontend
```

---

## 10. Useful Debug Commands

```bash
# Tail backend logs (shows migration output on startup)
docker-compose logs -f backend

# Tail Celery worker logs (shows pipeline steps and Ollama calls)
docker-compose logs -f celery_worker

# Open a Python shell inside the backend container
docker-compose exec backend python

# Check Redis claim status (key only exists while claim is in-flight)
docker-compose exec redis redis-cli get "claim_status:<your-claim-id>"

# Manually trigger the SSE endpoint (streams until claim completes)
curl -N http://localhost:8000/api/claims/<your-claim-id>/events

# Check Celery pipeline queue depth
docker-compose exec redis redis-cli llen "pipeline"

# Check Redis AOF persistence status
docker-compose exec redis redis-cli info persistence

# Query the claims table
docker-compose exec postgres psql -U claims -d claims_db \
  -c "SELECT id, status, decision, approved_amount FROM claims ORDER BY created_at DESC LIMIT 5;"

# Query claim history (fraud counters backing store)
docker-compose exec postgres psql -U claims -d claims_db \
  -c "SELECT member_id, treatment_date, claimed_amount, decision FROM claim_history ORDER BY created_at DESC LIMIT 10;"

# Query document embeddings
docker-compose exec postgres psql -U claims -d claims_db \
  -c "SELECT file_id, document_type, extraction_confidence, (diagnosis_embedding IS NOT NULL) AS has_embedding FROM documents;"

# Check HNSW index exists
docker-compose exec postgres psql -U claims -d claims_db \
  -c "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='documents' AND indexname LIKE '%hnsw%';"
```

---

## Environment Variables Reference

| Variable | Default in .env.example | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://claims:claims@postgres:5432/claims_db` | Async DB URL for FastAPI + Celery worker |
| `SYNC_DATABASE_URL` | `postgresql://claims:claims@postgres:5432/claims_db` | Sync URL for Alembic migrations |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection for status cache, fraud counters, SSE pub/sub |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama server URL for vision-based document extraction |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:3b` | Vision model name |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery task queue (DB1) |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery result storage (DB2) |
| `CELERY_WORKER_CONCURRENCY` | `4` | Number of concurrent tasks per worker container. Increase for CPU-heavy workloads; `docker compose up --scale celery_worker=N` adds more containers |
| `POLICY_FILE_PATH` | `/app/policy_terms.json` | Path to policy terms inside the container |
| `RUN_MIGRATIONS` | `true` (backend) / `false` (celery_worker) | Controls whether the entrypoint runs migrations + seed on startup |
