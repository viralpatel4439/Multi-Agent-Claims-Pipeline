# Architecture — Multi-Agent Health Insurance Claims Pipeline

## Overview

A multi-agent system that processes Indian health insurance claims end-to-end. A submitted claim passes through five agents — document verification, document extraction, policy compliance, fraud detection, and decision synthesis — and produces a final decision (`APPROVED` / `PARTIAL` / `REJECTED` / `MANUAL_REVIEW`) with a full audit trace. Policy compliance and fraud detection run in parallel (via `asyncio.gather`) inside the worker.

---

## High-Level Request Flow

```
Browser / API Client
        │
        │  POST /api/claims
        ▼
┌──────────────────────────────────────────────┐
│            FastAPI (port 8000)               │
│                                              │
│  ① Backpressure guard                        │
│     Queue depth > 500? → 429 (retry later)  │
│                                              │
│  ② Idempotency guard                         │
│     Same member + date + category +          │
│     amount already PENDING/PROCESSING/       │
│     COMPLETED? → return existing ID          │
│                                              │
│  ③ DocumentVerificationAgent (sync)          │
│     Wrong doc type / unreadable /            │
│     patient mismatch?                        │
│     → 422 immediately, no task queued        │
│                                              │
│  ④ Persist claim as PENDING to DB            │
│     Set Redis key → "PENDING"                │
│     Enqueue Celery task (queue: pipeline)    │
│     → 202 {claim_id}                         │
└──────────────────────────────────────────────┘
        │
        │  apply_async → Redis broker (DB1) → queue: pipeline
        ▼
┌──────────────────────────────────────────────┐
│           Celery Worker                      │
│                                              │
│  ⑤ Acquire NX lock                           │
│     SET pipeline_lock:{id} NX EX=720         │
│     Duplicate worker? → skip                 │
│                                              │
│  ⑥ Set Redis key → "PROCESSING"              │
│                                              │
│  ⑦ DocumentExtractionAgent (batch)           │
│     All docs → ONE Ollama call               │
│     file_path → PyMuPDF → JPEG →            │
│     Ollama qwen2.5vl:3b → JSON              │
│     OR content dict → direct map            │
│     + embed_batch(diagnosis or treatment)    │
│       → 384-dim vectors (all-MiniLM-L6-v2)  │
│                                              │
│  ⑧ Member lookup                             │
│     Redis member cache → hit?                │
│     No → DB → write back to cache (1h)       │
│                                              │
│  ⑨ asyncio.gather ──────────────────────┐    │
│     PolicyComplianceAgent               │    │
│     FraudDetectionAgent            ◄────┘    │
│     (run concurrently in the same            │
│      event loop — independent agents)        │
│                                              │
│  ⑩ DecisionEngine                            │
│     Synthesise → final decision +            │
│     confidence penalty for failures          │
│                                              │
│  ⑪ Persist COMPLETED/FAILED to DB           │
│     Write Document rows (with embeddings)    │
│     Write ClaimHistory row                   │
│     Publish → Redis claim_complete:{id}      │
│     DELETE Redis claim_status key            │
│     Release NX lock                          │
└──────────────────────────────────────────────┘
        │
        │  SSE push (or fallback REST poll)
        ▼
┌──────────────────────────────────────────────┐
│  GET /api/claims/{id}/events  (SSE)          │
│                                              │
│  Subscribe to claim_complete:{id} FIRST      │
│  then check Redis key                        │
│                                              │
│  Redis key exists?                           │
│  ├── YES → yield {status: PROCESSING}        │
│  │         wait for pub/sub message          │
│  │         → yield final DB result           │
│  └── NO  → claim already done               │
│            yield full DB result immediately  │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│     Frontend (Next.js, port 3000)            │
│     EventSource → instant result push        │
│     No repeated HTTP polling                 │
└──────────────────────────────────────────────┘
```

---

## Redis Strategy — Key Deletion + Pub/Sub Push

### Polling fallback (REST)

```
Claim submitted       Celery starts         Pipeline done
      │                    │                     │
      ▼                    ▼                     ▼
Redis SET "PENDING"   Redis SET "PROCESSING"  Redis DELETE key
                                                 + PUBLISH claim_complete
      └──────────────────────────────────────────┤
                                                 │
    GET /api/claims/{id}                         │
         │                                       │
         ├── Redis HIT → return status (no DB) ──┤
         │                                       │
         └── Redis MISS → read from DB ──────────┘
```

### SSE path (default for detail page)

The frontend opens `GET /api/claims/{id}/events`. The backend:

1. Subscribes to `claim_complete:{id}` **before** checking Redis (closes the race window).
2. Sends the current in-flight status immediately so the UI shows a spinner.
3. Blocks on `pubsub.listen()` — zero CPU, zero polling.
4. When the worker publishes to the channel, the backend fetches the full claim from DB and streams it as the final SSE frame.
5. Connection closes. Total HTTP requests: **1** (the SSE connection itself).

**Why deletion still matters:** The REST fallback (`GET /api/claims/{id}`) still uses the delete-as-signal pattern. In-flight polls hit Redis only; completion triggers one DB read. Both SSE and REST clients converge on the same final DB read.

---

## Backpressure

Before enqueuing any task, the API checks the Celery `pipeline` queue depth in Redis:

```python
depth = await redis.llen("pipeline")
if depth > 500:
    raise HTTPException(429, "Queue saturated — retry later")
```

This prevents runaway queue growth when workers are slower than the submission rate. Clients receive a clear 429 with `Retry-After` semantics instead of silently waiting for hours.

---

## Idempotency Guard

Before enqueuing a task, the API checks for an existing claim with the same `member_id + treatment_date + claim_category + claimed_amount` in `PENDING`, `PROCESSING`, or `COMPLETED` state. If found, it returns the existing `claim_id` immediately.

`FAILED` claims are excluded from this check — the member can resubmit after a pipeline failure.

---

## NX Lock — Preventing Duplicate Pipeline Runs

```python
SET pipeline_lock:{claim_id} 1 NX EX 720
```

A Redis `SET NX` is acquired before the pipeline starts. If two Celery workers somehow pick up the same task (e.g., after a broker restart), the second sees the lock held and skips. The lock is released in a `finally` block on normal exit — and also released **before** retrying on transient errors, so the retry can re-acquire it.

TTL of 720 s matches `task_time_limit` — the hard kill backstop if the worker crashes before `finally` runs.

---

## Task Retry Policy

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_full_pipeline(self, claim_id, claim_data):
    ...
    except (ConnectionError, TimeoutError, OperationalError, DisconnectionError):
        _redis.delete(lock_key)          # release lock before re-queuing
        raise self.retry(countdown=30 * 3**self.request.retries)  # 30s, 90s, 270s
```

Transient infrastructure failures (DB timeout, Redis blip, Ollama unavailable) automatically requeue with exponential backoff. Business-logic exceptions (policy rejection, extraction error) are not retried — they are handled gracefully inside each agent.

---

## Document Extraction — Vision Flow

When a real file (PDF or image) is uploaded, the extraction agent uses a local open-source vision model via Ollama:

```
User uploads file (PDF / JPG / PNG / WEBP)
        │
        ├── PDF  → PyMuPDF renders each page to JPEG (100 DPI, in-memory)
        └── Image → resize to max 1024px, JPEG quality 70 (in-memory)
        │
        ▼  ALL docs bundled into ONE HTTP call
HTTP POST → Ollama /api/chat (timeout: connect=10s, read=180s)
{
  "model": "qwen2.5vl:3b",
  "messages": [{"role": "user", "content": "<prompt>", "images": ["<b64>",...]}]
}
        │   Retry up to 3× on 5xx / timeout (5s → 15s → 45s backoff)
        ▼
_parse_json_safe() / _parse_json_array_safe()
        │
        ▼  LLM may return list for string fields — coerced by _coerce_str()
_build_extracted() → ExtractedDocument
        │
        ▼  embed_batch(diagnosis or treatment)  ← falls back to treatment if no diagnosis
all-MiniLM-L6-v2 → 384-dim vectors (one model.encode() call for all docs)
```

**Why `diagnosis or treatment` fallback:** A hospital bill has no diagnosis field. Using treatment text as the embedding source ensures every document produces a vector, enabling similarity search across all document types.

**Why Qwen2.5-VL over OCR + rules:** The assignment describes handwritten prescriptions, rubber stamps, and phone photos. Rule-based OCR mapping breaks on all three. A vision model reads the image as a human would.

**Local model setup:** https://github.com/viralpatel4439/Local-Model-Setup

---

## Container Startup Flow

```
backend container                       celery_worker container
─────────────────────────────────────   ─────────────────────────────────────
entrypoint.sh (RUN_MIGRATIONS=true)     entrypoint.sh (RUN_MIGRATIONS=false)
  │                                       │
  ├── alembic upgrade head                ├── [skipped]
  │     0001_initial                      │
  │     0002_add_raw_submission           │
  │     0003_scalability (HNSW index)     │
  │                                       │
  ├── python -m app.db.seed              ├── [skipped]
  │     INSERT ... ON CONFLICT UPDATE     │
  │                                       │
  └── exec uvicorn app.main:app          └── exec celery worker
                                               --queues=pipeline
                                               --concurrency=$CELERY_WORKER_CONCURRENCY
```

Only the backend runs migrations. By the time the worker picks up its first task, migrations are already applied and the HNSW index exists.

---

## Docker Services

| Service | Image / Source | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary database + vector similarity |
| `redis` | `redis:7-alpine` | 6379 | Claim status, Celery broker/results, fraud counters, member/policy cache, SSE pub/sub. **AOF persistence enabled.** |
| `backend` | `./backend/Dockerfile` | 8000 | FastAPI — doc verification, claim submission, SSE endpoint, REST poll endpoint |
| `celery_worker` | Same image as backend | — | Runs `run_full_pipeline` on `pipeline` queue. Scale with `--scale celery_worker=N` |
| `flower` | `mher/flower:2.0` | 5555 | Celery task monitoring |
| `frontend` | `./frontend/Dockerfile` | 3000 | Next.js 14 UI |

**Named volumes:**

| Volume | Mount | Purpose |
|---|---|---|
| `pgdata` | postgres `/var/lib/postgresql/data` | Postgres data |
| `redisdata` | redis `/data` | Redis AOF journal — fraud counters survive restarts |
| `uploads` | backend + celery_worker `/app/uploads` | Uploaded PDFs/images shared between API and worker |

**Ollama** runs externally (host or separate machine). Configure `OLLAMA_URL` in `.env`.

**Horizontal scaling:**
```bash
docker compose up -d --scale celery_worker=3
```
All worker replicas share the same `pipeline` queue in Redis and the same `uploads` volume. No other config change needed.

---

## Agent Details

### Agent 1 — DocumentVerificationAgent
**Runs: synchronously in the HTTP handler (not Celery)**

Catches document problems before any async work begins so errors surface as an immediate 422.

Checks (collects ALL issues, not just the first):
1. **WRONG_DOC_TYPE** — submitted types vs. `policy.document_requirements[claim_category].required`
2. **UNREADABLE** — any document with `quality == "UNREADABLE"`
3. **PATIENT_MISMATCH** — more than one unique `patient_name_on_doc` across documents

Returns `{valid: bool, issues: [{issue_type, file_id, message}]}`. If `valid=False` → 422, no Celery task enqueued.

**Source:** [backend/app/agents/document_verifier.py](backend/app/agents/document_verifier.py)

---

### Agent 2 — DocumentExtractionAgent
**Runs: inside Celery worker — all documents in ONE Ollama call**

| Mode | Trigger | Mechanism |
|---|---|---|
| **Vision** | `file_path` set | PyMuPDF/Pillow → JPEG (in-memory) → Ollama `qwen2.5vl:3b` → JSON parse |
| **Direct dict** | `content` dict, no `file_path` | Maps dict keys directly — used by all 12 test cases |
| **Passthrough** | Neither provided | Returns `extraction_confidence=0.3`, all fields null |

After extraction, `embed_batch(diagnosis or treatment)` produces 384-dim vectors in a single `model.encode()` call. Vectors are stored in `documents.diagnosis_embedding` (pgvector) and used for similarity search. `_coerce_str()` normalises any field the LLM returns as a list into a `"; "`-joined string before Pydantic validation.

**Source:** [backend/app/agents/document_extractor.py](backend/app/agents/document_extractor.py)

---

### Agent 3 — PolicyComplianceAgent
**Runs: inside Celery worker, pure Python — in parallel with FraudDetectionAgent**

10 ordered rule checks with full `trace_steps` audit log.

| Step | Check | Failure |
|---|---|---|
| 1 | 30-day initial waiting period | `WAITING_PERIOD` |
| 2 | Category covered | `CATEGORY_NOT_COVERED` |
| 3 | Global exclusions (diagnosis + treatment text) | `EXCLUDED_CONDITION` |
| 4 | Condition-specific waiting periods (diabetes=90d, maternity=270d…) | `WAITING_PERIOD` |
| 5 | Per-line-item exclusions → may produce PARTIAL | — |
| 6 | Pre-auth required for high-value tests | `PRE_AUTH_MISSING` |
| 7 | Per-claim ceiling = `max(sub_limit, global_per_claim_limit)` | `PER_CLAIM_EXCEEDED` |
| 8 | Sub-limit check (informational) | — |
| 9 | Network hospital discount | — |
| 10 | Co-pay deduction | — |

Formula: `final = (approved_line_items − network_discount) × (1 − copay_rate)`

**Source:** [backend/app/agents/policy_checker.py](backend/app/agents/policy_checker.py)

---

### Agent 4 — FraudDetectionAgent
**Runs: inside Celery worker — in parallel with PolicyComplianceAgent**

Reads Redis fraud counters for live deployments. In tests, uses `injected_claims_history` directly. On completion, the orchestrator writes a `ClaimHistory` row so fraud counters are backed by durable DB data, not just expiring Redis keys.

| Signal | Severity | Score |
|---|---|---|
| Same-day claims above `same_day_claims_limit` | HIGH | +0.5 |
| Monthly claims above `monthly_claims_limit` | MEDIUM | +0.2 |
| Amount above `high_value_claim_threshold` | MEDIUM | +0.2 |
| Amount above `auto_manual_review_above` | HIGH | +0.5 |
| Extraction confidence < 50% | LOW | +0.1 |

`recommendation = MANUAL_REVIEW` if `score ≥ 0.5` or any HIGH signal present.

**Source:** [backend/app/agents/fraud_detector.py](backend/app/agents/fraud_detector.py)

---

### Agent 5 — DecisionEngine
**Runs: inside Celery worker — after compliance and fraud complete**

1. Base decision from compliance (APPROVED / PARTIAL / REJECTED)
2. Fraud `MANUAL_REVIEW` overrides APPROVED or PARTIAL — not REJECTED
3. `confidence = base_confidence − (0.2 × len(failed_agents))`, clamped to [0, 1]
4. Assembles full `trace` (extraction, compliance steps, fraud signals, final decision)

**Source:** [backend/app/agents/decision_engine.py](backend/app/agents/decision_engine.py)

---

## Graceful Failure Handling

Every agent is individually wrapped in `try/except`. A failed agent appends to `failed_agents` and processing continues — downstream agents always have maximum available information.

```
Agent fails
    │
    ├── Appended to failed_agents list
    ├── Processing continues to next agent
    └── DecisionEngine: confidence -= 0.2 per failed agent
                        manual_review_note added to output
```

`asyncio.gather(..., return_exceptions=True)` is used for compliance and fraud — if either raises, the exception is caught and wrapped into a failed `AgentResult` without aborting the other.

---

## Data Layer

### PostgreSQL Tables

| Table | Key columns |
|---|---|
| `claims` | `id (UUID)`, `member_id`, `status`, `decision`, `approved_amount`, `confidence_score`, `rejection_reasons (JSONB)`, `trace (JSONB)`, `pipeline_errors (JSONB)`, `raw_submission (JSONB)` |
| `documents` | `id (UUID)`, `claim_id (FK)`, `document_type`, `extracted_data (JSONB)`, `diagnosis_embedding Vector(384)`, `processing_status`, `extraction_confidence` |
| `members` | `member_id (PK)`, `name`, `join_date`, `date_of_birth` |
| `claim_history` | `id (UUID)`, `member_id`, `claim_id`, `treatment_date`, `claimed_amount`, `provider`, `decision` |

**Indexes:**
- `claims`: `member_id`, `status`, `created_at`
- `documents`: `claim_id`, **HNSW on `diagnosis_embedding` (cosine, m=16, ef=64)** — added in migration 0003
- `claim_history`: `member_id`, `treatment_date`, composite `(member_id, treatment_date)`

`pgvector` extension enabled in migration 0001. HNSW index enables sub-linear cosine similarity search — critical beyond ~100k document rows.

### Redis Key Space

| Key | Value | TTL | Purpose |
|---|---|---|---|
| `claim_status:{claim_id}` | `{status, decision}` JSON | 24h safety net | In-flight status — **deleted** on pipeline completion to signal done |
| `pipeline_lock:{claim_id}` | `"1"` | 720s | NX lock — exactly-once execution across workers |
| `claim_complete:{claim_id}` | pub/sub channel | — | SSE push notification — published once on completion, subscribers receive it immediately |
| `member:{member_id}` | member JSON | 1h | Member data cache |
| `policy:{policy_id}` | policy JSON | 1h | Policy cache |
| `fraud:same_day:{member_id}:{date}` | int counter | Until midnight | Same-day fraud counter |
| `fraud:monthly:{member_id}:{YYYY-MM}` | int counter | 35 days | Monthly fraud counter |
| `embedding:model:loaded` | `"1"` | persistent | Health check flag |
| Celery broker tasks | — | — | Redis DB1, queue name: `pipeline` |
| Celery task results | — | 1h | Redis DB2 |

**Redis persistence:** AOF with `appendfsync everysec` — at most 1 second of counter/status data lost on a hard crash. Persisted to the `redisdata` Docker volume.

---

## Celery Configuration

```python
task_acks_late              = True    # Not acked until complete — survives worker crash
task_reject_on_worker_lost  = True    # Re-queues if worker process is killed mid-task
worker_prefetch_multiplier  = 1       # One task per slot — prevents starvation
worker_max_tasks_per_child  = 100     # Recycle worker after 100 tasks — bounds memory leaks
task_soft_time_limit        = 600     # Raises SoftTimeLimitExceeded for graceful shutdown
task_time_limit             = 720     # Hard kill after 12 min (matches NX lock TTL)
task_default_queue          = "pipeline"
result_expires              = 3600
```

`task_acks_late=True` + `task_reject_on_worker_lost=True` together ensure a task is never silently dropped: if a worker dies, the task goes back to the queue. The NX lock prevents the requeued task from double-processing a claim that partially completed.

---

## Services

| Service | Source | Purpose |
|---|---|---|
| `ollama_service` | [backend/app/services/ollama_service.py](backend/app/services/ollama_service.py) | Sends base64 JPEG images to Ollama `/api/chat`. Timeout: connect=10s, read=180s. Retries up to 3× on 5xx/timeout with 5s→15s→45s backoff |
| `embedding_service` | [backend/app/services/embedding_service.py](backend/app/services/embedding_service.py) | Lazy-loads `all-MiniLM-L6-v2` (~90MB). `embed_batch()` processes all docs in one `model.encode()` call. Returns `None` gracefully if unavailable |
| `policy_service` | [backend/app/services/policy_service.py](backend/app/services/policy_service.py) | Parses `policy_terms.json` into typed Pydantic models — in-process cache + Redis cache |
| `redis_service` | [backend/app/services/redis_service.py](backend/app/services/redis_service.py) | Async Redis client — claim status, NX lock, member/policy cache, fraud counters, SSE pub/sub publish, queue depth check |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/claims` | Backpressure check → idempotency guard → doc verification → DB persist → Redis SET → Celery enqueue. Returns 202 or 422 or 429. |
| `GET` | `/api/claims/{claim_id}/events` | **SSE stream.** Subscribes to Redis pub/sub, sends current status immediately, pushes final result when pipeline completes. One persistent connection replaces repeated polling. |
| `GET` | `/api/claims/{claim_id}` | REST fallback. Redis key present = in-flight (no DB). Key absent = done, read from DB. |
| `GET` | `/api/claims` | List 20 most recent claims (DB, paginated via `limit`/`offset`). |
| `POST` | `/api/claims/{claim_id}/rerun` | Reset claim state, clear NX lock, re-enqueue pipeline. |
| `POST` | `/api/upload` | Upload PDF/image (≤ 20 MB). Saves to `/app/uploads/` (shared Docker volume). Returns `file_path`. |
| `GET` | `/api/members` | All policy members for frontend dropdown. |
| `GET` | `/api/health` | DB connectivity, Redis ping, embedding model loaded flag. |

---

## Frontend

Next.js 14 app at port 3000.

- **`/` (ClaimForm)** — member dropdown, category, treatment date, claimed amount, hospital name. Each document card has a file upload button (PDF/PNG/JPG/WEBP ≤ 20 MB) that calls `POST /api/upload` immediately on select and stores `file_path`. JSON content textarea available as an alternative. `simulate_failure` checkbox for TC011. On 422 shows per-issue errors; on 202 navigates to `/claims/{id}`.

- **`/claims`** — paginated table of all claims with status badge, amounts, and links to detail. **Adaptive polling:** 3 s intervals for the first 30 s after an in-flight claim is detected, backing off to 8 s intervals after that — reduces DB load by ~60% for long-running claims.

- **`/claims/[id]`** — opens a `GET /api/claims/{id}/events` SSE connection on mount, seeds the React-Query cache with the initial HTTP fetch, then updates it instantly when the pipeline publishes its completion event. No repeated polling. Renders decision banner, confidence score, financial breakdown, policy compliance trace, fraud signals, and per-agent trace accordion.

---

## Dependency Split

| Environment | File | Includes |
|---|---|---|
| Local / tests | `requirements-dev.txt` | FastAPI, SQLAlchemy, Celery, Redis, httpx, pytest, **fpdf2** |
| Docker / production | `requirements.txt` | All above + **torch**, **sentence-transformers**, **pgvector**, **pymupdf** |

`torch`, `sentence-transformers`, and `pymupdf` are Docker-only. `embed_text()` / `embed_batch()` return `None` when the model is unavailable so all tests pass offline.

---

## Trade-offs and Decisions

| Decision | Rationale |
|---|---|
| Redis key deleted (not set to COMPLETED) on finish | Absence is the signal — in-flight polls are Redis-only (zero DB load), completion triggers a single DB read. Both SSE and REST consumers benefit from this |
| SSE with subscribe-before-check pattern | Eliminates the race condition where a claim completes between the status check and the pub/sub subscription; prevents hanging SSE connections |
| `asyncio.gather` for compliance + fraud | Both agents are pure-Python/Redis, independent, and async-native. `gather` runs them in the same event loop concurrently without spawning additional Celery tasks — zero orchestration overhead |
| NX lock released before retry | `self.retry()` raises `Retry` which triggers `finally`, releasing the lock. The re-queued task then re-acquires it cleanly — no deadlock risk |
| `task_reject_on_worker_lost + task_acks_late` | Together prevent silent task loss on worker crash; combined with the NX lock this gives exactly-once semantics |
| `worker_max_tasks_per_child=100` | The sentence-transformers model and PyMuPDF can accumulate heap fragmentation; recycling after 100 tasks keeps RSS bounded |
| HNSW over IVFFlat for pgvector | HNSW is index-only (no training phase, no approximate nlist tuning). Safe to create at migration time on an empty table; IVFFlat requires a pre-populated table |
| AOF `appendfsync everysec` over `always` | `always` fsyncs on every write (throughput kills fraud counter increments). `everysec` loses at most 1 second of data on crash — acceptable for counters backed by `claim_history` |
| Named `pipeline` queue | Workers started with `--queues=pipeline` are dedicatedly scalable: `docker compose up --scale celery_worker=3` adds capacity without changing any other config |
| `uploads` named Docker volume (not S3) | Keeps the stack self-contained for local/demo use. Backend and all worker replicas share the volume. For production with workers on separate hosts, replace with a shared NFS mount or object store |
| `all-MiniLM-L6-v2` for embeddings | Smallest sentence-transformers model under 200 MB with acceptable quality for medical text similarity. No cloud dependency |

---

## Scalability Status

Items addressed in this codebase:

| Item | Status |
|---|---|
| Parallel compliance + fraud (asyncio.gather) | ✅ Implemented |
| HNSW pgvector index | ✅ Migration 0003 |
| Ollama retry + timeout | ✅ Implemented |
| Task retries on transient errors | ✅ max_retries=3, exponential backoff |
| Worker memory leak guard | ✅ worker_max_tasks_per_child=100 |
| Task re-queue on worker crash | ✅ task_reject_on_worker_lost=True |
| SSE push (replaces frontend polling) | ✅ Implemented |
| Backpressure (429 on queue saturation) | ✅ queue depth > 500 → 429 |
| Durable fraud history | ✅ ClaimHistory written on every completed claim |
| Redis AOF persistence | ✅ appendonly + redisdata volume |
| Horizontal worker scaling | ✅ named queue + --scale flag |
| Document embeddings persisted to DB | ✅ Document rows written in _persist |

Items remaining for production at very high scale (>1M claims/year):

| Item | What's needed |
|---|---|
| Redis Cluster / Sentinel | Single Redis is still a SPOF; Sentinel adds HA failover |
| Postgres read replicas | Route poll reads to replica, writes to primary |
| Object storage for uploads | Replace named volume with S3/MinIO for multi-host worker deployments |
| Rate limiting per member/IP | `slowapi` or a Redis-based token bucket on POST /api/claims |
