# Component Contracts

Each section defines the interface for one component: its input, output, and the errors it can produce. An engineer should be able to reimplement any single component from these specs without reading its source.

---

## 1. DocumentVerificationAgent

**Location:** `backend/app/agents/document_verifier.py`  
**Runs:** Synchronously in the FastAPI HTTP handler — before any claim is persisted or queued.

### Input

```python
run(
    documents: list[DocumentInput],
    claim_category: str,          # e.g. "CONSULTATION", "PHARMACY", "DENTAL"
    member_id: str,
)
```

**`DocumentInput` fields used:**

| Field | Type | Purpose |
|---|---|---|
| `file_id` | `str` | Unique identifier for this document |
| `file_name` | `str \| None` | Human-readable name for error messages |
| `actual_type` | `str` | Type declared by the submitter (e.g. `"PRESCRIPTION"`, `"HOSPITAL_BILL"`) |
| `quality` | `str \| None` | `"GOOD"` or `"UNREADABLE"` |
| `patient_name_on_doc` | `str \| None` | Patient name visible on the document |

### Output

`AgentResult` with `data`:

```json
{
  "valid": true | false,
  "issues": [
    {
      "issue_type": "WRONG_DOC_TYPE | UNREADABLE | PATIENT_MISMATCH",
      "file_id": "F001 | null",
      "message": "<human-readable string naming exactly what is wrong and what is needed>"
    }
  ]
}
```

- `valid = false` → HTTP 422 is returned immediately; no Celery task is queued.
- `issues` collects **all** problems found, not just the first.
- `message` is always specific: it names the uploaded type, the required type, the affected filenames, and the corrective action.

### Issue types

| `issue_type` | Trigger | `file_id` |
|---|---|---|
| `WRONG_DOC_TYPE` | A required document type for the claim category is absent from the submitted set | `null` (category-level, not per-file) |
| `UNREADABLE` | A document has `quality == "UNREADABLE"` | The `file_id` of that document |
| `PATIENT_MISMATCH` | More than one distinct `patient_name_on_doc` across all documents | `null` (claim-level) |

### Errors

| Condition | Behaviour |
|---|---|
| Policy does not define document requirements for this `claim_category` | Skips type check; continues unreadable + mismatch checks |
| Unexpected exception | Returns `AgentResult(success=False, data={"valid": False, "issues": []}, error=<str>)` |

---

## 2. DocumentExtractionAgent

**Location:** `backend/app/agents/document_extractor.py`  
**Runs:** Inside the Celery worker. All documents are batched into **one** Ollama call.

### Input

```python
run(
    document: DocumentInput,
    simulate_failure: bool = False,   # Forces an error for TC011
)
```

**`DocumentInput` fields used:**

| Field | Type | Extraction path |
|---|---|---|
| `file_path` | `str \| None` | Vision path: file → JPEG (PyMuPDF / Pillow) → Ollama |
| `content` | `dict \| None` | Direct map path: dict keys → `ExtractedDocument` fields |

Exactly one of `file_path` or `content` should be set. If neither is set, the agent returns a passthrough result with `extraction_confidence=0.3`.

### Output

`AgentResult` with `data` matching `ExtractedDocument`:

```json
{
  "document_type": "PRESCRIPTION",
  "patient_name": "Rajesh Kumar",
  "doctor_name": "Dr. Arun Sharma",
  "doctor_registration": "KA/45678/2015",
  "diagnosis": "Viral Fever",
  "treatment": null,
  "date": "2024-11-01",
  "line_items": [{"description": "Consultation Fee", "amount": 1000}],
  "total_amount": 1500,
  "medicines": ["Paracetamol 650mg"],
  "tests_ordered": [],
  "hospital_name": null,
  "extraction_confidence": 0.95,
  "fields_low_confidence": [],
  "diagnosis_embedding": [0.12, -0.34, ...]   // 384-dim float vector, null if model unavailable
}
```

### Extraction paths

| Path | Trigger | Notes |
|---|---|---|
| **Vision** | `file_path` is set | PDF → PyMuPDF → JPEG (100 DPI); Image → resize max 1024px, JPEG quality 70. All pages/images batched into one Ollama request. |
| **Direct dict** | `content` is set, no `file_path` | Struct fields mapped directly; `extraction_confidence = 0.95` |
| **Passthrough** | Neither set | Returns nulls with `extraction_confidence = 0.3` |

### Errors

| Condition | Behaviour |
|---|---|
| Ollama timeout or 5xx | Retried up to 3× (5s → 15s → 45s backoff). Returns `success=False` after all retries |
| `simulate_failure=True` | Returns `AgentResult(success=False, error="Simulated component failure")` |
| JSON parse failure | `_parse_json_safe()` returns `{}` → passthrough result |
| LLM returns list for string field | `_coerce_str()` joins with `"; "` |
| Embedding model unavailable | `diagnosis_embedding = null`; rest of extraction unaffected |

---

## 3. PolicyComplianceAgent

**Location:** `backend/app/agents/policy_checker.py`  
**Runs:** Inside the Celery worker, in parallel with `FraudDetectionAgent` via `asyncio.gather`.

### Input

```python
run(
    claim: ClaimSubmissionRequest,
    extracted_docs: list[ExtractedDocument],
    member_join_date: date,
    member_name: str,
)
```

**`ClaimSubmissionRequest` fields used:**

| Field | Type |
|---|---|
| `member_id` | `str` |
| `claim_category` | `str` |
| `treatment_date` | `date` |
| `claimed_amount` | `float` |
| `hospital_name` | `str \| None` |

### Output

`AgentResult` with `data`:

```json
{
  "decision": "APPROVED | PARTIAL | REJECTED",
  "approved_amount": 1350.0,
  "rejection_reasons": ["WAITING_PERIOD"],
  "reason_text": "Human-readable explanation",
  "confidence": 0.9,
  "line_item_decisions": [
    {
      "description": "Root Canal Treatment",
      "amount": 8000,
      "status": "APPROVED | EXCLUDED",
      "reason": null | "Teeth whitening is an excluded dental procedure"
    }
  ],
  "financial_breakdown": {
    "claimed_amount": 4500,
    "approved_before_network_discount": 4500,
    "network_discount_rate": 0.20,
    "network_discount_amount": 900,
    "amount_after_network_discount": 3600,
    "copay_rate": 0.10,
    "copay_amount": 360,
    "final_approved_amount": 3240
  },
  "waiting_period_eligible_from": "2024-11-30",
  "trace_steps": [
    {"step": 1, "name": "30-day initial waiting period", "passed": true, "detail": "..."}
  ]
}
```

### Rule execution order

| Step | Check | Failure result |
|---|---|---|
| 1 | 30-day initial waiting period from `member_join_date` | `REJECTED`, reason `WAITING_PERIOD` |
| 2 | Category covered in policy | `REJECTED`, reason `CATEGORY_NOT_COVERED` |
| 3 | Global exclusions (diagnosis + treatment text, **not** line items) | `REJECTED`, reason `EXCLUDED_CONDITION` |
| 4 | Condition-specific waiting periods (diabetes=90d, maternity=270d, etc.) | `REJECTED`, reason `WAITING_PERIOD`; sets `waiting_period_eligible_from` |
| 5 | Per-line-item exclusion scan | `PARTIAL` if any excluded; approved total = sum of non-excluded items |
| 6 | Pre-authorisation (MRI/CT/PET above threshold) | `REJECTED`, reason `PRE_AUTH_MISSING` |
| 7 | Per-claim ceiling = `max(category_sub_limit, global_per_claim_limit)` | `REJECTED`, reason `PER_CLAIM_EXCEEDED` |
| 8 | Sub-limit informational check | Logged in trace only |
| 9 | Network hospital discount | `approved -= approved × network_discount_rate` |
| 10 | Co-pay deduction | `final = post_discount × (1 - copay_rate)` |

Steps 1–6 are **early exits**: a failure stops further checks and returns immediately.

### Errors

| Condition | Behaviour |
|---|---|
| `extracted_docs` is empty | Rules run against `claimed_amount` only; no line-item check |
| Policy not found for `claim_category` | Returns `MANUAL_REVIEW`, reason `COMPLIANCE_CHECK_FAILED` |
| Unexpected exception | Returns `AgentResult(success=False, ...)` |

---

## 4. FraudDetectionAgent

**Location:** `backend/app/agents/fraud_detector.py`  
**Runs:** Inside the Celery worker, in parallel with `PolicyComplianceAgent`.

### Input

```python
run(
    claim: ClaimSubmissionRequest,
    extracted_docs: list[ExtractedDocument],
    injected_claims_history: list[dict] | None = None,
)
```

- If `injected_claims_history` is provided (used in tests), Redis counters are bypassed.
- Otherwise, live Redis counters (`fraud:same_day:{member_id}:{date}`, `fraud:monthly:{member_id}:{YYYY-MM}`) are read.

**`claims_history` item shape:**

```json
{"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"}
```

### Output

`AgentResult` with `data`:

```json
{
  "fraud_score": 0.5,
  "recommendation": "PASS | MANUAL_REVIEW",
  "signals": [
    {
      "type": "SAME_DAY_CLAIMS",
      "severity": "HIGH",
      "description": "4 claims submitted on 2024-10-30 (limit: 2)",
      "score_contribution": 0.5
    }
  ]
}
```

### Signals

| Signal | Severity | Score | Trigger |
|---|---|---|---|
| `SAME_DAY_CLAIMS` | HIGH | +0.5 | Same-day count > `same_day_claims_limit` (default: 2) |
| `HIGH_MONTHLY_FREQUENCY` | MEDIUM | +0.2 | Monthly count > `monthly_claims_limit` |
| `HIGH_VALUE_CLAIM` | MEDIUM | +0.2 | `claimed_amount` > `high_value_claim_threshold` |
| `AUTO_MANUAL_REVIEW` | HIGH | +0.5 | `claimed_amount` > `auto_manual_review_above` |
| `LOW_EXTRACTION_CONFIDENCE` | LOW | +0.1 | Any doc `extraction_confidence < 0.5` |

`recommendation = "MANUAL_REVIEW"` if `fraud_score >= 0.5` **or** any signal has severity `HIGH`.

### Errors

| Condition | Behaviour |
|---|---|
| Redis unavailable | Falls back to `injected_claims_history` if provided; otherwise skips counter checks |
| Unexpected exception | Returns `AgentResult(success=False, ...)` |

---

## 5. DecisionEngine

**Location:** `backend/app/agents/decision_engine.py`  
**Runs:** Inside the Celery worker — after compliance and fraud both complete.

### Input

```python
run(
    claim: ClaimSubmissionRequest,
    extraction_results: list[AgentResult],
    compliance_result: AgentResult,
    fraud_result: AgentResult,
    failed_agents: list[str],
)
```

- `failed_agents`: names of any agents that returned `success=False` before this step.

### Output

`AgentResult` with `data`:

```json
{
  "decision": "APPROVED | PARTIAL | REJECTED | MANUAL_REVIEW",
  "approved_amount": 3240.0,
  "confidence_score": 0.85,
  "rejection_reasons": [],
  "decision_reason": "Claim approved. Network discount and co-pay applied.",
  "line_item_decisions": [...],
  "financial_breakdown": {...},
  "waiting_period_eligible_from": null,
  "fraud_signals": [],
  "failed_components": [],
  "manual_review_note": null,
  "trace": {
    "document_extraction": [...],
    "policy_compliance": {"success": true, "trace_steps": [...], "error": null},
    "fraud_detection": {"success": true, "fraud_score": 0.0, "signals": [], "recommendation": "PASS"},
    "final_decision": {"decision": "APPROVED", "approved_amount": 3240.0, "confidence_score": 0.85, "rejection_reasons": [], "failed_components": []}
  }
}
```

### Synthesis rules

| Rule | Detail |
|---|---|
| Base decision | Taken from `compliance_result.data.decision` |
| Fraud override | If `fraud_result.data.recommendation == "MANUAL_REVIEW"` and base decision is not `REJECTED` → decision becomes `MANUAL_REVIEW`, `FRAUD_SIGNAL_DETECTED` added to rejection reasons |
| Confidence penalty | `confidence = base_confidence − (0.2 × len(failed_agents))`, clamped to [0.0, 1.0] |
| Failed component note | If `failed_agents` is non-empty: `manual_review_note` is populated; the compliance decision is **not** overridden |
| Compliance failure | If `compliance_result.success=False`: decision defaults to `MANUAL_REVIEW`, `base_confidence = 0.3` |

### Errors

| Condition | Behaviour |
|---|---|
| Unexpected exception in `_synthesize` | Returns `AgentResult(success=False, data=None, error=<str>)` — this is the only error path; all synthesis logic is defensive |

---

## 6. POST /api/claims

**Location:** `backend/app/api/claims.py`

### Input

HTTP `POST /api/claims` with JSON body `ClaimSubmissionRequest`:

```json
{
  "member_id": "EMP001",
  "policy_id": "GHI_2024",
  "claim_category": "CONSULTATION",
  "treatment_date": "2024-11-01",
  "claimed_amount": 1500.0,
  "hospital_name": "Apollo Hospitals",
  "documents": [
    {
      "file_id": "F007",
      "actual_type": "PRESCRIPTION",
      "quality": "GOOD",
      "patient_name_on_doc": "Rajesh Kumar",
      "file_path": "/app/uploads/uuid.pdf",
      "content": null
    }
  ],
  "simulate_component_failure": false,
  "claims_history": null
}
```

### Output

| HTTP Status | Condition | Body |
|---|---|---|
| `202 Accepted` | Claim queued successfully | `{"claim_id": "<uuid>"}` |
| `200 OK` | Duplicate claim already exists (idempotency hit) | `{"claim_id": "<existing-uuid>"}` |
| `422 Unprocessable Entity` | Document verification failed | `{"detail": [{"issue_type": "...", "file_id": "...", "message": "..."}]}` |
| `429 Too Many Requests` | Pipeline queue depth > 500 | `{"detail": "Queue saturated — retry later"}` |

### Errors

| Condition | Behaviour |
|---|---|
| Member not in policy | Proceeds; member is looked up by `member_id` from DB |
| Policy file not found | 500 on startup; not a per-request error |

---

## 7. GET /api/claims/{claim_id}/events (SSE)

**Location:** `backend/app/api/claims.py`

### Input

`GET /api/claims/{claim_id}/events`  
`Accept: text/event-stream`

### Output stream

```
data: {"status": "PROCESSING", "claim_id": "<uuid>"}

data: {"claim_id": "...", "status": "COMPLETED", "decision": "APPROVED", "approved_amount": 1350.0, "confidence_score": 0.9, "rejection_reasons": [], "decision_reason": "...", "trace": {...}, "created_at": "..."}
```

- Frame 1 arrives immediately (current in-flight status from Redis).
- Frame 2 arrives when the Celery worker publishes to `claim_complete:{claim_id}` channel. No polling — zero CPU between frames.
- Connection closes after frame 2.
- If the claim is already `COMPLETED` when the SSE request arrives, only one frame is sent (the final result).

### Errors

| Condition | Behaviour |
|---|---|
| Claim not found in Redis or DB | Yields `{"status": "NOT_FOUND"}` and closes |
| Redis pub/sub unavailable | Falls back to single DB read, yields result, closes |

---

## 8. POST /api/upload

**Location:** `backend/app/api/upload.py`

### Input

`POST /api/upload` with `multipart/form-data`, field name `file`.

- Accepted MIME types: `application/pdf`, `image/jpeg`, `image/png`, `image/webp`
- Max size: 20 MB

### Output

```json
{"file_path": "/app/uploads/a1b2c3d4-filename.pdf"}
```

Use the returned `file_path` as `documents[n].file_path` in the subsequent `POST /api/claims` request. The path is accessible to the Celery worker via the shared `uploads` Docker volume.

### Errors

| Condition | HTTP status |
|---|---|
| Unsupported file type | `415 Unsupported Media Type` |
| File exceeds 20 MB | `413 Request Entity Too Large` |
| Write failure | `500` |
