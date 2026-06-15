# Architecture — Multi-Agent Health Insurance Claims Pipeline

## Overview

A multi-agent system that processes Indian health insurance claims end-to-end. A submitted claim passes through five sequential agents — document verification, document extraction, policy compliance, fraud detection, and decision synthesis — and produces a final decision (`APPROVED` / `PARTIAL` / `REJECTED` / `MANUAL_REVIEW`) with a full audit trace.

---

## High-Level Request Flow

```
Browser / API Client
        │
        │  POST /api/claims
        ▼
┌─────────────────────────────────────────┐
│           FastAPI (port 8000)           │
│                                         │
│  ① Idempotency guard                   │
│     Same member + date + category +     │
│     amount already PENDING/PROCESSING/  │
│     COMPLETED? → return existing ID     │
│                                         │
│  ② DocumentVerificationAgent (sync)    │
│     Wrong doc type / unreadable /       │
│     patient mismatch?                   │
│     → 422 immediately, no task queued   │
│                                         │
│  ③ Persist claim as PENDING to DB      │
│     Set Redis key → "PENDING"           │
│     Enqueue Celery task                 │
│     → 202 {claim_id}                    │
└─────────────────────────────────────────┘
        │
        │  apply_async → Redis broker (DB1)
        ▼
┌─────────────────────────────────────────┐
│        Celery Worker                    │
│                                         │
│  ④ Acquire NX lock                     │
│     SET pipeline_lock:{id} NX EX=600    │
│     Duplicate worker? → skip            │
│                                         │
│  ⑤ Set Redis key → "PROCESSING"        │
│                                         │
│  ⑥ DocumentExtractionAgent × N (seq)  │
│     file_path → PyMuPDF → PNG →        │
│     Ollama qwen2.5vl:3b → JSON         │
│     OR content dict → direct map       │
│     + embed diagnosis (MiniLM-L6-v2)   │
│                                         │
│  ⑦ Member lookup                       │
│     Redis member cache → hit?           │
│     No → DB → write back to cache (1h) │
│                                         │
│  ⑧ PolicyComplianceAgent              │
│     10-step rule checks (pure Python)   │
│                                         │
│  ⑨ FraudDetectionAgent               │
│     Redis fraud counters +              │
│     pgvector similarity search          │
│                                         │
│  ⑩ DecisionEngine                     │
│     Synthesise → final decision +       │
│     confidence penalty for failures     │
│                                         │
│  ⑪ Persist COMPLETED/FAILED to DB     │
│     DELETE Redis claim_status key       │
│     Release NX lock                     │
└─────────────────────────────────────────┘
        │
        │  Frontend polls GET /api/claims/{id} every 2s
        ▼
┌─────────────────────────────────────────┐
│  GET /api/claims/{id}                   │
│                                         │
│  Redis key exists?                      │
│  ├── YES → claim still in-flight        │
│  │         return {status: PROCESSING}  │
│  │         (no DB hit)                  │
│  └── NO  → claim done (key was deleted) │
│            read full result from DB     │
│            return decision + trace      │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│     Frontend (Next.js, port 3000)       │
│     Decision card + Trace viewer        │
└─────────────────────────────────────────┘
```

---

## Redis Strategy — Why Deletion is the Signal

This is the core scalability decision in the polling design.

```
Claim submitted       Celery starts         Pipeline done
      │                    │                     │
      ▼                    ▼                     ▼
Redis SET "PENDING"   Redis SET "PROCESSING"  Redis DELETE key
      │                    │                     │
      └──────────┬──────────┘                    │
                 │                               │
    Frontend polls GET /claims/{id}              │
         │                                       │
         ├── Redis HIT → return status directly ─┤ (no DB query)
         │                                       │
         └── Redis MISS → read from DB ──────────┘ (single read on completion)
```

**Why not keep the key after completion?** If the key held `COMPLETED`, every subsequent poll or page refresh would hit Redis but then still need to read the full trace from DB anyway. Deleting the key makes the absence itself the signal — the first miss triggers one DB read and that's it. During processing, all polls are Redis-only with no DB load.

**TTL safety net:** The Redis key has a 24h TTL as a fallback. If the worker crashes before it can delete the key, the key expires naturally and the next poll falls through to DB, which will show the last-written status.

---

## Idempotency Guard

Before enqueuing a task, the API checks for an existing claim with the same `member_id + treatment_date + claim_category + claimed_amount` in `PENDING`, `PROCESSING`, or `COMPLETED` state. If found, it returns the existing `claim_id` immediately.

`FAILED` claims are excluded from this check — the member can resubmit after a pipeline failure.

---

## NX Lock — Preventing Duplicate Pipeline Runs

```python
SET pipeline_lock:{claim_id} 1 NX EX 600
```

A Redis `SET NX` (set-if-not-exists) is acquired before the pipeline starts. If two Celery workers somehow pick up the same task (e.g., after a broker restart), the second one sees the lock already held and skips. The lock is released in a `finally` block on normal exit. TTL of 600s is the hard backstop if the worker crashes before `finally` runs.

---

## Document Extraction — Vision Flow

When a real file (PDF or image) is uploaded, the extraction agent uses a local open-source vision model via Ollama:

```
User uploads file (PDF / JPG / PNG)
        │
        ├── PDF → PyMuPDF renders each page → PNG bytes (200 DPI)
        └── Image → read bytes directly
        │
        ▼
base64.b64encode(png_bytes)
        │
        ▼  HTTP POST → Ollama /api/chat
{
  "model": "qwen2.5vl:3b",
  "messages": [{
    "role": "user",
    "content": "<vision extraction prompt>",
    "images": ["<base64 string>"]
  }]
}
        │
        ▼
_parse_json_safe() → ExtractedDocument
        │
        ▼  (multi-page PDFs)
_merge_page_results()
  - line_items / medicines / tests_ordered → accumulated across pages
  - patient_name / diagnosis / etc. → first non-null wins
  - extraction_confidence → minimum across pages
```

**Why Qwen2.5-VL over OCR + rules:** The assignment describes handwritten prescriptions, rubber stamps, and phone photos. Rule-based OCR mapping breaks on all three. A vision model reads the image as a human would.

**Why PyMuPDF:** Ollama accepts images (base64 PNG/JPEG), not PDF files. PyMuPDF renders pages to pixels at 200 DPI before the encode step.

**Local model setup:** [https://github.com/viralpatel4439/Local-Model-Setup](https://github.com/viralpatel4439/Local-Model-Setup)

---

## Container Startup Flow

The backend and celery_worker share the same Docker image but have different startup behaviour controlled by the `RUN_MIGRATIONS` env var.

```
backend container                       celery_worker container
─────────────────────────────────────   ─────────────────────────────────────
entrypoint.sh (RUN_MIGRATIONS=true)     entrypoint.sh (RUN_MIGRATIONS=false)
  │                                       │
  ├── alembic upgrade head                ├── [skipped]
  │     checks alembic_version table      │
  │     only runs unapplied revisions     │
  │     idempotent on every restart       │
  │                                       │
  ├── python -m app.db.seed              ├── [skipped]
  │     INSERT ... ON CONFLICT UPDATE     │
  │     safe to run every startup         │
  │                                       │
  └── exec uvicorn app.main:app          └── exec celery worker ...
```

Only the backend runs migrations. The celery_worker sets `RUN_MIGRATIONS=false` so it starts immediately without racing to create the `alembic_version` table. By the time the worker picks up its first task, migrations are already applied.

---

## Docker Services

| Service | Image / Source | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary database + vector similarity |
| `redis` | `redis:7-alpine` | 6379 | Claim status (DB0), Celery broker (DB1), result backend (DB2), fraud counters, member/policy cache |
| `backend` | `./backend/Dockerfile` | 8000 | FastAPI — sync doc verification + claim submission + polling endpoint |
| `celery_worker` | Same image as backend | — | Runs `run_full_pipeline` task |
| `flower` | `mher/flower:2.0` | 5555 | Celery task monitoring |
| `frontend` | `./frontend/Dockerfile` | 3000 | Next.js 14 UI |

**Ollama** runs externally. Configure `OLLAMA_URL` in `.env` to point to it. See [Local-Model-Setup](https://github.com/viralpatel4439/Local-Model-Setup).

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
**Runs: inside Celery worker, once per document**

| Mode | Trigger | Mechanism |
|---|---|---|
| **Vision** | `file_path` set | PyMuPDF → PNG pages → Ollama `qwen2.5vl:3b` → JSON parse |
| **Direct dict** | `content` dict, no `file_path` | Maps dict keys directly — used by all 12 test cases |
| **Passthrough** | Neither provided | Returns `extraction_confidence=0.3`, all fields null |

After extraction, `embedding_service.embed_text(diagnosis)` produces a 384-dim vector stored in `diagnosis_embedding` for pgvector duplicate-claim similarity checks.

**Source:** [backend/app/agents/document_extractor.py](backend/app/agents/document_extractor.py)

---

### Agent 3 — PolicyComplianceAgent
**Runs: inside Celery worker, pure Python**

10 ordered rule checks with full `trace_steps` audit log. Returns early on first terminal failure.

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
**Runs: inside Celery worker**

Reads Redis fraud counters for live deployments. In tests, uses `injected_claims_history` directly (offline, no Redis needed).

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
**Runs: inside Celery worker**

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

No crash = no data loss. A claim with three failed agents still produces a decision at `confidence = base − 0.6`, flagged for manual review.

---

## Data Layer

### PostgreSQL Tables

| Table | Key columns |
|---|---|
| `claims` | `id (UUID)`, `member_id`, `status`, `decision`, `approved_amount`, `confidence_score`, `rejection_reasons (JSONB)`, `trace (JSONB)`, `pipeline_errors (JSONB)` |
| `documents` | `id (UUID)`, `claim_id (FK)`, `document_type`, `quality`, `content (JSONB)`, `extracted_data (JSONB)`, `diagnosis_embedding (Vector(384))` |
| `members` | `member_id (PK)`, `name`, `join_date`, `date_of_birth` |
| `claim_history` | `id (UUID)`, `member_id`, `treatment_date`, `claimed_amount`, `decision` |

`pgvector` extension enabled in migration 0001. `Vector(384)` uses cosine distance (`<=>`) for duplicate-claim similarity search.

### Redis Key Space

| Key | Value | TTL | Purpose |
|---|---|---|---|
| `claim_status:{claim_id}` | `{status, decision}` JSON | 24h (safety net) | In-flight status for frontend polling — **deleted** on pipeline completion |
| `pipeline_lock:{claim_id}` | `"1"` | 600s | NX lock — prevents duplicate pipeline runs across workers |
| `member:{member_id}` | member JSON | 1h | Member data cache — avoids repeated DB lookups in the pipeline |
| `policy:{policy_id}` | policy JSON | 1h | Policy cache — also held in-process via `_policy_cache` global |
| `fraud:same_day:{member_id}:{date}` | int counter | Until midnight | Same-day fraud detection counter |
| `fraud:monthly:{member_id}:{YYYY-MM}` | int counter | 35 days | Monthly fraud detection counter |
| `embedding:model:loaded` | `"1"` | persistent | Health check flag — set when MiniLM model finishes loading |
| Celery broker tasks | — | — | Redis DB1 |
| Celery task results | — | 1h | Redis DB2 |

**Key insight:** `claim_status` is the only key that gets **deleted** (not expired). Every other key expires naturally. Deletion is used as an out-of-band signal that the pipeline has finished — this avoids any extra notification mechanism between the Celery worker and the FastAPI polling endpoint.

---

## Celery Configuration

```python
task_acks_late          = True   # Task not acked until complete — survives worker crash
worker_prefetch_multiplier = 1   # One task per worker — prevents task starvation
task_soft_time_limit    = 120    # Raises SoftTimeLimitExceeded for graceful shutdown
task_time_limit         = 180    # Hard kill after 3 min — prevents zombie tasks
result_expires          = 3600   # Celery result backend TTL
```

`task_acks_late=True` is important for reliability: if a worker dies mid-pipeline, the task goes back to the queue rather than being lost. Combined with the NX lock, a requeued task will re-acquire the lock and rerun cleanly.

---

## Services

| Service | Source | Purpose |
|---|---|---|
| `ollama_service` | [backend/app/services/ollama_service.py](backend/app/services/ollama_service.py) | Sends base64 PNG images to Ollama `/api/chat`, returns raw model text |
| `embedding_service` | [backend/app/services/embedding_service.py](backend/app/services/embedding_service.py) | Lazy-loads `all-MiniLM-L6-v2` (~90MB). Returns `None` gracefully if unavailable. **Docker only** |
| `policy_service` | [backend/app/services/policy_service.py](backend/app/services/policy_service.py) | Parses `policy_terms.json` into typed Pydantic models — in-process cache + Redis cache |
| `redis_service` | [backend/app/services/redis_service.py](backend/app/services/redis_service.py) | Async Redis client — claim status, NX lock, member cache, policy cache, fraud counters, health flag |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/claims` | Submit claim. Idempotency check → doc verification → DB persist → Redis SET → Celery enqueue. Returns 202 or 422. |
| `GET` | `/api/claims/{claim_id}` | Redis first: key present = in-flight (no DB). Key absent = done, read from DB. |
| `GET` | `/api/claims` | List 20 most recent claims (DB, paginated via `limit`/`offset`). |
| `POST` | `/api/upload` | Upload PDF/image (≤ 20 MB). Saves to `/app/uploads/` (shared volume between backend + celery_worker). Returns `file_path` used in claim submission. |
| `GET` | `/api/members` | All policy members for frontend dropdown. |
| `GET` | `/api/health` | Checks DB connectivity, Redis ping, and embedding model loaded flag. |

---

## Frontend

Next.js 14 app at port 3000.

- **`/` (ClaimForm)** — member dropdown, category, treatment date, claimed amount, hospital name. Each document card has a **file upload button** (PDF/PNG/JPG/WEBP ≤ 20 MB) that calls `POST /api/upload` immediately on select and stores the returned `file_path`. JSON content textarea is available as an alternative (used by automated tests). `simulate_failure` checkbox for TC011. On 422 shows specific per-issue error messages; on 202 navigates to `/claims/{id}`.
- **`/claims`** — paginated table of all submitted claims with status badge, amounts, and links to detail. Auto-refreshes every 3s if any claim is in PENDING/PROCESSING state.
- **`/claims/[id]`** — polls `GET /api/claims/{id}` every 2s until status leaves PENDING/PROCESSING. Renders decision banner (green/yellow/red/orange), confidence score, financial breakdown, policy compliance trace steps, fraud signals, and per-agent trace accordion.

---

## Dependency Split

| Environment | File | Includes |
|---|---|---|
| Local / tests | `requirements-dev.txt` | FastAPI, SQLAlchemy, Celery, Redis, httpx, pytest, **fpdf2** (sample doc generation) |
| Docker / production | `requirements.txt` | All above + **torch**, **sentence-transformers**, **pgvector**, **pymupdf** |

`torch`, `sentence-transformers`, and `pymupdf` are Docker-only. `embed_text()` returns `None` when the model is unavailable so all tests pass offline. `fpdf2` is dev-only — used to generate the four sample documents in `tests/sample_documents/`.

---

## Trade-offs and Limitations

| Decision | Rationale |
|---|---|
| Redis key deleted (not set to COMPLETED) on finish | Makes absence the signal — in-flight polls are Redis-only (zero DB load), completion triggers a single DB read |
| NX lock at Celery level not Postgres level | Celery guarantees at-least-once delivery. The NX lock converts that to exactly-once execution per claim without a DB transaction |
| Idempotency at API level (not task level) | Catches duplicate submissions before they enter the queue — cheaper than deduplication inside Celery |
| Ollama over cloud vision API | No API cost, runs fully local, handles all document quality variations in the assignment |
| Single monolithic Celery task | Simple failure boundary — one `try/except` per agent, one lock, one persist. At 10x load this splits into a Celery chord (see below) |
| `all-MiniLM-L6-v2` (~90MB) for embeddings | Smallest sentence-transformers model under 200MB with acceptable quality. No cloud dependency |
| No learning/template system for OCR | Vision model handles all layout variability without stored templates. Template caching is a valid optimisation at high volume but premature here |

---

## Scalability Path (10× — ~750k claims/year)

```
Current (monolithic task)          10× (chord + horizontal scale)
─────────────────────────          ────────────────────────────────
Single run_full_pipeline           chord([extract_doc.s(doc) for doc in docs])
  Extract A                          | fan-out — parallel per document
  Extract B         →                └─ callback: compliance → fraud → decision
  Compliance
  Fraud
  Decision
```

Specific changes needed:
- Split `run_full_pipeline` into a Celery **chord** — parallel extraction per document, fan-in to policy/fraud/decision
- **Redis Cluster** for fraud counters (single Redis is the bottleneck at high write volume)
- **Read replicas** on Postgres — polling reads (`GET /claims/{id}`) go to replica, writes stay on primary
- **pgvector index** (`ivfflat` or `hnsw`) on `diagnosis_embedding` — similarity search degrades linearly without an index beyond ~100k rows
- **Document template cache** in Postgres — store layout embeddings + field positions for known form types; skip Ollama for repeat templates
- **Pre-warm MiniLM** in each worker process at startup rather than on first request
- Move `policy_service` cache to Redis only (remove in-process global) — safe for multi-process workers
