# Architecture — Multi-Agent Health Insurance Claims Pipeline

## Overview

A multi-agent system that processes Indian health insurance claims end-to-end. A submitted claim passes through five sequential agents — document verification, document extraction, policy compliance, fraud detection, and decision synthesis — and produces a final decision (APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW) with a full audit trace.

---

## High-Level Request Flow

```
Browser / API Client
        │
        │  POST /api/claims
        ▼
┌───────────────────────────────────┐
│         FastAPI (port 8000)       │
│                                   │
│  1. DocumentVerificationAgent     │  ◄─ Runs synchronously in the HTTP handler
│     • Wrong doc type?             │
│     • Unreadable quality?         │
│     • Patient name mismatch?      │
│                                   │
│  If issues → 422 immediately      │
│  (TC001, TC002, TC003)            │
│                                   │
│  If valid → persist PENDING       │
│            set Redis status       │
│            enqueue Celery task    │
│  Response: 202 {claim_id}         │
└───────────────────────────────────┘
        │
        │  apply_async → Redis (broker DB1)
        ▼
┌───────────────────────────────────┐
│     Celery Worker (run_full_pipeline) │
│                                   │
│  2. DocumentExtractionAgent × N   │  ◄─ One per submitted document
│     • NVIDIA NIM (LLM mode)       │
│     • Direct dict (fallback mode) │
│     • Embeds diagnosis via        │
│       sentence-transformers       │
│                                   │
│  3. PolicyComplianceAgent         │  ◄─ Pure Python logic, no LLM
│     10-step ordered rule checks   │
│                                   │
│  4. FraudDetectionAgent           │  ◄─ Redis counters + scoring
│     Same-day / monthly / value    │
│                                   │
│  5. DecisionEngine                │  ◄─ Synthesises all results
│     Confidence penalty for        │
│     failed components             │
│                                   │
│  6. Persist to PostgreSQL         │
│     Update Redis status           │
└───────────────────────────────────┘
        │
        │  GET /api/claims/{id}  (polled every 2s)
        ▼
┌───────────────────────────────────┐
│     Frontend (Next.js, port 3000) │
│     Decision card + Trace viewer  │
└───────────────────────────────────┘
```

---

## Docker Services

| Service | Image / Source | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary database + vector similarity |
| `redis` | `redis:7-alpine` | 6379 | Celery broker (DB1), result backend (DB2), status cache (DB0), fraud counters |
| `backend` | `./backend/Dockerfile` | 8000 | FastAPI app — handles HTTP and document verification |
| `celery_worker` | Same image as backend | — | Runs the monolithic `run_full_pipeline` Celery task |
| `flower` | `mher/flower:2.0` | 5555 | Celery task monitoring dashboard |
| `frontend` | `./frontend/Dockerfile` | 3000 | Next.js 14 UI for claim submission and trace viewing |

The frontend calls the backend directly at `http://localhost:8000/api` — no reverse proxy is in place.

---

## Agent Details

### Agent 1 — DocumentVerificationAgent
**Runs: synchronously in the HTTP handler (not Celery)**

Catches document problems before any async work begins so errors surface as an immediate 422, not after polling.

Checks in order (collects ALL issues, not just first):
1. **WRONG_DOC_TYPE** — matches submitted types against `policy.document_requirements[claim_category].required`
2. **UNREADABLE** — any document with `quality == "UNREADABLE"`
3. **PATIENT_MISMATCH** — more than one unique `patient_name_on_doc` across all documents

Returns `{valid: bool, issues: [{issue_type, file_id, message}]}`. If `valid=False`, the API returns 422 and no Celery task is enqueued.

**Source:** [backend/app/agents/document_verifier.py](backend/app/agents/document_verifier.py)

---

### Agent 2 — DocumentExtractionAgent
**Runs: inside Celery worker, once per document**

Extracts structured fields (patient name, diagnosis, doctor, line items, amounts) from each document.

Two modes selected at runtime:
- **NVIDIA LLM mode** — when `NVIDIA_API_KEY` is set, sends the document content JSON to `minimaxai/minimax-m3` via `nvidia_service.get_completion()` and parses the response JSON.
- **Direct dict mode** — when `self.client is None` (tests, or no API key), reads directly from the structured `content` dict. This is how all 12 test cases run without touching the NVIDIA API.

After extraction, `embedding_service.embed_text(diagnosis)` produces a 384-dimensional vector stored in `diagnosis_embedding` (used later for pgvector duplicate-claim checks).

**Source:** [backend/app/agents/document_extractor.py](backend/app/agents/document_extractor.py)

---

### Agent 3 — PolicyComplianceAgent
**Runs: inside Celery worker, pure Python**

Applies 10 ordered rule checks and builds a full `trace_steps` audit log. Returns early on first terminal failure (no point checking sub-limits if the waiting period fails).

| Step | Check | Failure reason |
|---|---|---|
| 1 | 30-day initial waiting period | `WAITING_PERIOD` |
| 2 | Category is covered | `CATEGORY_NOT_COVERED` |
| 3 | Global exclusions (diagnosis + treatment text) | `EXCLUDED_CONDITION` |
| 4 | Condition-specific waiting periods (diabetes=90d, maternity=270d, …) | `WAITING_PERIOD` |
| 5 | Per-line-item exclusions → may produce PARTIAL | — |
| 6 | Pre-authorization required for high-value tests above threshold | `PRE_AUTH_MISSING` |
| 7 | Per-claim ceiling = `max(category_sub_limit, global_per_claim_limit)` | `PER_CLAIM_EXCEEDED` |
| 8 | Sub-limit (informational, already enforced by step 7) | — |
| 9 | Network hospital discount (applied first) | — |
| 10 | Co-pay deduction (applied after discount) | — |

Financial formula: `final = (approved_line_items − network_discount) × (1 − copay_rate)`

**Source:** [backend/app/agents/policy_checker.py](backend/app/agents/policy_checker.py)

---

### Agent 4 — FraudDetectionAgent
**Runs: inside Celery worker**

Scores signals and recommends MANUAL_REVIEW if score ≥ 0.5 or any HIGH-severity signal is present.

| Signal | Severity | Score |
|---|---|---|
| Same-day claims above `policy.fraud_thresholds.same_day_claims_limit` | HIGH | +0.5 |
| Monthly claims above limit | MEDIUM | +0.2 |
| Claimed amount above `high_value_claim_threshold` | MEDIUM | +0.2 |
| Claimed amount above `auto_manual_review_above` | HIGH | +0.5 |
| Document extraction confidence < 50% | LOW | +0.1 |

In tests, `injected_claims_history` is passed directly instead of querying Redis, so fraud checks work fully offline.

**Source:** [backend/app/agents/fraud_detector.py](backend/app/agents/fraud_detector.py)

---

### Agent 5 — DecisionEngine
**Runs: inside Celery worker**

Synthesises all previous results into one final decision:

1. Takes compliance decision as base (APPROVED / PARTIAL / REJECTED)
2. Fraud MANUAL_REVIEW overrides compliance APPROVED or PARTIAL (not REJECTED — a fraudulent rejected claim stays REJECTED)
3. Confidence penalty: `confidence = base_confidence − (0.2 × len(failed_agents))`, clamped to [0, 1]
4. If any agent failed, adds `manual_review_note` to the output
5. Assembles the full `trace` dict (extraction, compliance steps, fraud signals, final decision)

**Source:** [backend/app/agents/decision_engine.py](backend/app/agents/decision_engine.py)

---

## Data Layer

### PostgreSQL Tables

| Table | Key columns |
|---|---|
| `claims` | `id (UUID)`, `member_id`, `status`, `decision`, `approved_amount`, `confidence_score`, `rejection_reasons (JSONB)`, `trace (JSONB)`, `pipeline_errors (JSONB)` |
| `documents` | `id (UUID)`, `claim_id (FK)`, `document_type`, `quality`, `content (JSONB)`, `extracted_data (JSONB)`, `diagnosis_embedding (Vector(384))` |
| `members` | `member_id (PK)`, `name`, `join_date`, `date_of_birth` |
| `claim_history` | `id (UUID)`, `member_id`, `treatment_date`, `claimed_amount`, `decision` |

`pgvector` extension is enabled in the first Alembic migration. `Vector(384)` columns use cosine distance (`<=>`) for duplicate-claim similarity search.

### Redis Key Space

| Key | Purpose | TTL |
|---|---|---|
| `claim_status:{claim_id}` | Fast-path status for frontend polling | 24h |
| `fraud:same_day:{member_id}:{date}` | Same-day claim count | Expires at midnight |
| `fraud:monthly:{member_id}:{YYYY-MM}` | Monthly claim count | 35 days |
| Celery broker | Redis DB1 | — |
| Celery results | Redis DB2 | — |

---

## Services

| Service | Source | Purpose |
|---|---|---|
| `nvidia_service` | [backend/app/services/nvidia_service.py](backend/app/services/nvidia_service.py) | Async `get_completion(model, message)` wrapper around the NVIDIA NIM API |
| `embedding_service` | [backend/app/services/embedding_service.py](backend/app/services/embedding_service.py) | Lazy-loads `all-MiniLM-L6-v2` (sentence-transformers). **Docker only.** |
| `policy_service` | [backend/app/services/policy_service.py](backend/app/services/policy_service.py) | Parses `policy_terms.json` into typed Pydantic models, cached in Redis |
| `redis_service` | [backend/app/services/redis_service.py](backend/app/services/redis_service.py) | Async Redis client — claim status, fraud counters |

---

## Celery Pipeline

Single monolithic task `run_full_pipeline` in [backend/app/pipeline/orchestrator.py](backend/app/pipeline/orchestrator.py).

```
process_claim(claim_id, claim_data)
  └─ run_full_pipeline.apply_async(args=[claim_id, claim_data], queue="default")
       │
       ├─ Step 1: DocumentExtractionAgent × N (sequential)
       ├─ Step 2: DB lookup for member join_date
       ├─ Step 3: PolicyComplianceAgent
       ├─ Step 4: FraudDetectionAgent
       ├─ Step 5: DecisionEngine
       └─ Step 6: _persist() → DB + Redis
```

Every step is individually try/caught. A failed agent is added to `failed_agents` and processing continues so downstream agents have maximum information available. The DecisionEngine penalises confidence for each failed component.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/claims` | Submit a claim. Runs doc verification sync; enqueues pipeline on success. Returns 202 or 422. |
| `GET` | `/api/claims/{claim_id}` | Fetch claim status and decision. Redis fast-path for PENDING/PROCESSING; DB for completed. |
| `GET` | `/api/claims` | List 20 most recent claims. |
| `GET` | `/api/members` | All policy members (for frontend dropdown). |
| `GET` | `/api/health` | DB, Redis, and Celery connectivity check. |

---

## Frontend

Next.js 14 app at port 3000.

- **`/` (ClaimForm)** — member dropdown, category, treatment date, claimed amount, hospital name, dynamic document list with type + quality + JSON content fields, `simulate_failure` checkbox. On 422 shows specific per-issue error messages. On 202 navigates to `/claims/{id}`.
- **`/claims/[id]`** — polls `GET /api/claims/{id}` every 2 seconds until status is COMPLETED or FAILED. Displays decision banner (green/yellow/red/orange), confidence score, financial breakdown table, per-agent trace accordion.

---

## Dependency Split

| Environment | Requirements file | Includes |
|---|---|---|
| Local (tests only) | `requirements-dev.txt` | FastAPI, SQLAlchemy, Celery, Redis, httpx, pytest |
| Docker (full runtime) | `requirements.txt` | All of the above + `torch`, `sentence-transformers`, `pgvector` |

`torch` and `sentence-transformers` are **Docker-only**. The embedding service handles `ImportError` gracefully — `embed_text()` returns `None` when the model is unavailable, so tests pass without those packages installed.

---

## Test Coverage

29 pytest tests, all passing locally with `requirements-dev.txt`.

| Test module | What it covers |
|---|---|
| `test_agents/test_document_verifier.py` | All 3 verification rule types |
| `test_agents/test_document_extractor.py` | Structured extraction, fallback, simulate_failure |
| `test_agents/test_policy_checker.py` | Waiting periods, exclusions, partial, pre-auth, limits, financials |
| `test_agents/test_fraud_detector.py` | Same-day fraud, high-value, clean pass |
| `test_cases/test_all_12_cases.py` | All 12 assignment test cases end-to-end (TC001–TC012) |

The `DocumentExtractionAgent` uses `self.client = None` in tests (no `NVIDIA_API_KEY` set) which forces direct dict extraction — deterministic and API-free.
