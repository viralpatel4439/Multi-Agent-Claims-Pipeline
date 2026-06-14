# Execution Guide

## Prerequisites

- Docker Desktop (Mac/Windows/Linux)
- Python 3.12+ (for local test runs only)
- An NVIDIA NIM API key from [build.nvidia.com](https://build.nvidia.com) (only needed for live LLM extraction; tests work without it)

---

## 1. Environment Setup

Copy the example env file and fill in your key:

```bash
cp .env.example .env
```

Edit `.env` and set your real key:

```
NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx
```

All other values work as-is for local Docker use.

---

## 2. Run Everything in Docker

```bash
docker-compose up -d
```

This starts: postgres, redis, backend (FastAPI), celery_worker, flower, frontend.

Wait for services to be healthy (about 20–30 seconds):

```bash
docker-compose ps
```

All services should show `running` or `healthy`.

---

## 3. Database Migration + Seed

Run once after first `docker-compose up`:

```bash
# Create tables and enable pgvector extension
docker-compose exec backend alembic upgrade head

# Seed 12 members + TC009 pre-existing claim history
docker-compose exec backend python -m app.db.seed
```

---

## 4. Verify the Stack

```bash
curl http://localhost:8000/api/health
```

Expected:

```json
{"db": "ok", "redis": "ok", "celery": "ok"}
```

---

## 5. Access the UI

| URL | What it is |
|---|---|
| `http://localhost:3000` | Claim submission form |
| `http://localhost:8000/api/docs` | FastAPI Swagger UI |
| `http://localhost:5555` | Flower — Celery task monitor |

---

## 6. Manual End-to-End Test (TC004 — APPROVED)

Submit a TC004-equivalent claim through the UI:

1. Open `http://localhost:3000`
2. Select member **EMP001**, category **CONSULTATION**, hospital **Apollo Hospitals** (network)
3. Treatment date: **2024-11-15**, claimed amount: **1500**
4. Add one document — type **PRESCRIPTION**, quality **GOOD**, patient name **Rajesh Kumar**
5. Submit → redirected to `/claims/{id}`
6. Wait ~2–5 seconds for polling to resolve
7. Expected: **APPROVED**, approved amount **₹1,350** (10% co-pay on ₹1,500)

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

### Run all 29 tests

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

To also remove the database volume (wipes all data):

```bash
docker-compose down -v
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
# Tail backend logs
docker-compose logs -f backend

# Tail Celery worker logs
docker-compose logs -f celery_worker

# Open a Python shell inside the backend container
docker-compose exec backend python

# Check Redis claim status directly
docker-compose exec redis redis-cli get "claim_status:<your-claim-id>"

# Query the database
docker-compose exec postgres psql -U claims -d claims_db -c "SELECT id, status, decision, approved_amount FROM claims ORDER BY created_at DESC LIMIT 5;"
```

---

## Environment Variables Reference

| Variable | Default in .env.example | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://claims:claims@postgres:5432/claims_db` | Async DB URL for FastAPI + Celery worker |
| `SYNC_DATABASE_URL` | `postgresql://claims:claims@postgres:5432/claims_db` | Sync URL for Alembic migrations |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection for status cache + fraud counters |
| `NVIDIA_API_KEY` | *(fill in)* | NVIDIA NIM API key for LLM document extraction |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery task queue |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery result storage |
| `POLICY_FILE_PATH` | `/app/policy_terms.json` | Path to policy terms inside the container |
