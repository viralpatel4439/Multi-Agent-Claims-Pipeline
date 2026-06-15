# Eval Report — 12 Test Cases

All 12 test cases from `test_cases.json` were run through the full agent pipeline.  
Test command (inside Docker): `docker-compose exec backend python3 -m pytest tests/test_cases/test_all_12_cases.py -v`

**Result: 12/12 PASSED**

---

## Summary

| Case | Name | Expected Decision | Actual Decision | Match | Approved Amount |
|---|---|---|---|---|---|
| TC001 | Wrong Document Uploaded | VALIDATION_FAIL | VALIDATION_FAIL | ✅ | — |
| TC002 | Unreadable Document | VALIDATION_FAIL | VALIDATION_FAIL | ✅ | — |
| TC003 | Documents Belong to Different Patients | VALIDATION_FAIL | VALIDATION_FAIL | ✅ | — |
| TC004 | Clean Consultation — Full Approval | APPROVED | APPROVED | ✅ | ₹1,350 |
| TC005 | Waiting Period — Diabetes | REJECTED | REJECTED | ✅ | ₹0 |
| TC006 | Dental Partial Approval — Cosmetic Exclusion | PARTIAL | PARTIAL | ✅ | ₹8,000 |
| TC007 | MRI Without Pre-Authorization | REJECTED | REJECTED | ✅ | ₹0 |
| TC008 | Per-Claim Limit Exceeded | REJECTED | REJECTED | ✅ | ₹0 |
| TC009 | Fraud Signal — Multiple Same-Day Claims | MANUAL_REVIEW | MANUAL_REVIEW | ✅ | ₹0 |
| TC010 | Network Hospital — Discount Applied | APPROVED | APPROVED | ✅ | ₹3,240 |
| TC011 | Component Failure — Graceful Degradation | APPROVED | APPROVED | ✅ | ₹3,600 |
| TC012 | Excluded Treatment | REJECTED | REJECTED | ✅ | ₹0 |

---

## Case-by-Case Results

---

### TC001 — Wrong Document Uploaded

**What was submitted:** Two `PRESCRIPTION` documents for a `CONSULTATION` claim. `CONSULTATION` requires both a `PRESCRIPTION` and a `HOSPITAL_BILL`.

**System output (DocumentVerificationAgent):**
```json
{
  "valid": false,
  "issues": [
    {
      "issue_type": "WRONG_DOC_TYPE",
      "file_id": null,
      "message": "Document type HOSPITAL_BILL is required for CONSULTATION claims. You uploaded: PRESCRIPTION, PRESCRIPTION. Please provide a HOSPITAL_BILL document."
    }
  ]
}
```

**HTTP response:** `422 Unprocessable Entity` returned immediately. No claim queued.

**Match:** ✅ — The error names the missing type (`HOSPITAL_BILL`), the uploaded types (`PRESCRIPTION, PRESCRIPTION`), and instructs the member what to provide. No generic error.

---

### TC002 — Unreadable Document

**What was submitted:** `PHARMACY` claim with a valid `PRESCRIPTION` and a `PHARMACY_BILL` with `quality: UNREADABLE`.

**System output (DocumentVerificationAgent):**
```json
{
  "valid": false,
  "issues": [
    {
      "issue_type": "UNREADABLE",
      "file_id": "F004",
      "message": "Document 'blurry_bill.jpg' (type: PHARMACY_BILL) cannot be read — the image is too blurry or low quality. Please re-upload a clear photo or scan of this document."
    }
  ]
}
```

**HTTP response:** `422`. The claim is not rejected outright — the member is instructed to re-upload only the blurry document.

**Match:** ✅ — Identifies `F004` specifically; does not reject the entire claim; message is actionable.

---

### TC003 — Documents Belong to Different Patients

**What was submitted:** `CONSULTATION` claim for EMP001 (`Rajesh Kumar`) with a `PRESCRIPTION` showing `patient_name_on_doc: Rajesh Kumar` and a `HOSPITAL_BILL` showing `patient_name_on_doc: Arjun Mehta`.

**System output (DocumentVerificationAgent):**
```json
{
  "valid": false,
  "issues": [
    {
      "issue_type": "PATIENT_MISMATCH",
      "file_id": null,
      "message": "The documents you uploaded belong to different patients. All documents for a single claim must be for the same patient. Details: 'prescription_rajesh.jpg' (type: PRESCRIPTION) — patient name: 'Rajesh Kumar'; 'bill_arjun.jpg' (type: HOSPITAL_BILL) — patient name: 'Arjun Mehta'"
    }
  ]
}
```

**Match:** ✅ — Both names surfaced explicitly; both document names included; no claim decision made.

---

### TC004 — Clean Consultation — Full Approval

**What was submitted:** EMP001 (`join_date: 2024-04-01`) submitting `CONSULTATION` on `2024-11-01`. ₹1,500 claimed. Hospital: `City Clinic` (non-network). Documents: PRESCRIPTION + HOSPITAL_BILL (clean, matching patient names).

**Policy rules applied:**
- Initial 30-day WP: passed (joined Apr 2024, claim Nov 2024)
- Category `CONSULTATION`: covered
- No global exclusions
- No condition-specific WP matches (Viral Fever)
- Line items: all covered
- No pre-auth required (no MRI/CT/PET)
- Per-claim ceiling: `max(consultation.sub_limit=2000, global_per_claim_limit=5000) = 5000` — ₹1,500 < ₹5,000 ✓
- Network discount: 0% (City Clinic not a network hospital)
- Co-pay: 10% on ₹1,500 = ₹150 deducted

**System output:**
```json
{
  "decision": "APPROVED",
  "approved_amount": 1350.0,
  "confidence_score": 0.9,
  "rejection_reasons": [],
  "decision_reason": "Claim approved after all policy checks passed.",
  "financial_breakdown": {
    "claimed_amount": 1500,
    "network_discount_rate": 0.0,
    "network_discount_amount": 0,
    "amount_after_network_discount": 1500,
    "copay_rate": 0.10,
    "copay_amount": 150,
    "final_approved_amount": 1350
  }
}
```

**Match:** ✅ — Decision `APPROVED`, amount ₹1,350, confidence > 0.85.

---

### TC005 — Waiting Period — Diabetes

**What was submitted:** EMP005 (`join_date: 2024-09-01`) claiming for `Type 2 Diabetes Mellitus` on `2024-10-15` — 44 days after joining. The policy enforces a 90-day waiting period for diabetes.

**Policy rules applied:**
- Initial 30-day WP: passed (44 days > 30)
- Category: covered
- Condition-specific WP: `diabetes` matched in diagnosis (`Metformin 500mg`, `Glimepiride 1mg`). WP = 90 days. `2024-09-01 + 90d = 2024-11-30`. Treatment on `2024-10-15` is before `2024-11-30` → **REJECTED**
- `waiting_period_eligible_from` set to `"2024-11-30"`

**System output:**
```json
{
  "decision": "REJECTED",
  "approved_amount": 0,
  "rejection_reasons": ["WAITING_PERIOD"],
  "decision_reason": "Treatment falls within the 90-day waiting period for diabetes. Member is eligible from 2024-11-30.",
  "waiting_period_eligible_from": "2024-11-30"
}
```

**Match:** ✅ — `REJECTED`, reason `WAITING_PERIOD`, eligible date `2024-11-30` visible in output.

---

### TC006 — Dental Partial Approval — Cosmetic Exclusion

**What was submitted:** EMP002, `DENTAL` claim, ₹12,000. Bill contains two line items: `Root Canal Treatment` (₹8,000) and `Teeth Whitening` (₹4,000).

**Policy rules applied:**
- Global exclusion check: `teeth whitening` is in the combined text but exclusion check uses **diagnosis + treatment only** (not line items), so no global REJECTED
- Per-line-item scan: `"teeth whitening"` matched in `dental.excluded_procedures` → that item excluded
- Approved total: ₹8,000 (Root Canal only)
- No network discount (Smile Dental Clinic not network)
- Co-pay: dental copay = 0%

**System output:**
```json
{
  "decision": "PARTIAL",
  "approved_amount": 8000.0,
  "rejection_reasons": [],
  "line_item_decisions": [
    {"description": "Root Canal Treatment", "amount": 8000, "status": "APPROVED", "reason": null},
    {"description": "Teeth Whitening", "amount": 4000, "status": "EXCLUDED", "reason": "Teeth whitening is an excluded dental procedure under this policy."}
  ]
}
```

**Match:** ✅ — `PARTIAL`, ₹8,000, line-item breakdown shows which item was excluded and why.

---

### TC007 — MRI Without Pre-Authorization

**What was submitted:** EMP007, `DIAGNOSTIC` claim for `MRI Lumbar Spine` costing ₹15,000. No pre-authorization was obtained.

**Policy rules applied:**
- `"mri"` matched in combined text (tests_ordered + line item descriptions)
- `claimed_amount = 15000 > pre_auth_threshold = 10000` → `PRE_AUTH_MISSING`

**System output:**
```json
{
  "decision": "REJECTED",
  "approved_amount": 0,
  "rejection_reasons": ["PRE_AUTH_MISSING"],
  "decision_reason": "Pre-authorization is required for MRI/CT/PET procedures above ₹10,000. This claim for ₹15,000 was not pre-authorized. Please obtain pre-authorization from Plum before undergoing high-value diagnostic procedures and resubmit."
}
```

**Match:** ✅ — `REJECTED`, reason `PRE_AUTH_MISSING`.

---

### TC008 — Per-Claim Limit Exceeded

**What was submitted:** EMP003, `CONSULTATION` claim, ₹7,500.

**Policy rules applied:**
- Effective per-claim ceiling = `max(consultation.sub_limit=2000, global_per_claim_limit=5000) = 5000`
- ₹7,500 > ₹5,000 → `PER_CLAIM_EXCEEDED`

**System output:**
```json
{
  "decision": "REJECTED",
  "approved_amount": 0,
  "rejection_reasons": ["PER_CLAIM_EXCEEDED"],
  "decision_reason": "Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000 for CONSULTATION. Maximum claimable per claim is ₹5,000."
}
```

**Match:** ✅ — `REJECTED`, reason `PER_CLAIM_EXCEEDED`, limit and claimed amount both stated.

---

### TC009 — Fraud Signal — Multiple Same-Day Claims

**What was submitted:** EMP008, `CONSULTATION`, ₹4,800. `claims_history` shows 3 prior claims already submitted on `2024-10-30`. This is the 4th claim (same-day limit: 2).

**Fraud detection:**
- `same_day_count = 4 (3 history + current) > limit = 2`
- Signal `SAME_DAY_CLAIMS` severity `HIGH`, score contribution `+0.5`
- `fraud_score = 0.5` → `recommendation = MANUAL_REVIEW`

**Decision engine:**
- Base decision from compliance: `APPROVED` (claim itself is policy-compliant)
- Fraud override: `MANUAL_REVIEW` (fraud recommendation overrides non-REJECTED base)

**System output:**
```json
{
  "decision": "MANUAL_REVIEW",
  "fraud_signals": [
    {
      "type": "SAME_DAY_CLAIMS",
      "severity": "HIGH",
      "description": "4 claims submitted on 2024-10-30 (limit: 2)",
      "score_contribution": 0.5
    }
  ],
  "rejection_reasons": ["FRAUD_SIGNAL_DETECTED"]
}
```

**Match:** ✅ — `MANUAL_REVIEW`, unusual same-day pattern flagged, specific signal included. Not auto-rejected.

---

### TC010 — Network Hospital — Discount Applied

**What was submitted:** EMP010, `CONSULTATION`, ₹4,500, hospital: `Apollo Hospitals` (a network hospital).

**Policy rules applied:**
- All category and exclusion checks pass
- Network hospital check: `Apollo Hospitals` is in `network_hospitals` list → 20% discount
- Financial calculation (order matters):
  1. Claimed amount: ₹4,500
  2. Network discount (20%): ₹900 deducted → ₹3,600
  3. Co-pay (10%): ₹360 deducted → **₹3,240**

**System output:**
```json
{
  "decision": "APPROVED",
  "approved_amount": 3240.0,
  "financial_breakdown": {
    "claimed_amount": 4500,
    "network_discount_rate": 0.20,
    "network_discount_amount": 900,
    "amount_after_network_discount": 3600,
    "copay_rate": 0.10,
    "copay_amount": 360,
    "final_approved_amount": 3240
  }
}
```

**Match:** ✅ — `APPROVED`, ₹3,240. Network discount applied **before** co-pay. Breakdown visible.

---

### TC011 — Component Failure — Graceful Degradation

**What was submitted:** EMP006, `ALTERNATIVE_MEDICINE` (Panchakarma Therapy), ₹4,000. `simulate_component_failure: true` — causes the `DocumentExtractionAgent` to fail on the first document.

**Pipeline behavior:**
- `DocumentExtractionAgent` returns `AgentResult(success=False, error="Simulated component failure")` for document F021
- `failed_agents = ["DocumentExtractionAgent"]`
- Extraction for F022 (HOSPITAL_BILL) succeeds; extracted `total_amount = 4000` used
- `PolicyComplianceAgent` runs with partial extraction — claim passes all checks (alternative medicine is covered, ₹4,000 is within limits, no exclusions)
- `DecisionEngine`:
  - Base decision: `APPROVED`, `base_confidence = 0.9`
  - Confidence penalty: `0.9 − (0.2 × 1) = 0.7`
  - `failed_components = ["DocumentExtractionAgent"]`
  - `manual_review_note` populated

**System output:**
```json
{
  "decision": "APPROVED",
  "approved_amount": 3600.0,
  "confidence_score": 0.7,
  "failed_components": ["DocumentExtractionAgent"],
  "manual_review_note": "Manual review recommended: the following pipeline components failed during processing: DocumentExtractionAgent. Decision was made with incomplete information.",
  "rejection_reasons": []
}
```

**Match:** ✅ — No crash; decision is `APPROVED` (not overridden to MANUAL_REVIEW); confidence reduced from 0.9 to 0.7; `failed_components` and `manual_review_note` visible.

**Note on design decision:** The assignment says the pipeline must "continue and produce a decision." The code does not override the compliance decision to `MANUAL_REVIEW` when a component fails — it preserves `APPROVED` while surfacing the failure via `failed_components` and reducing confidence. This satisfies the assignment requirement for graceful degradation without hiding the failure.

---

### TC012 — Excluded Treatment

**What was submitted:** EMP009, `CONSULTATION`, ₹8,000. Diagnosis: `Morbid Obesity — BMI 37`. Treatment: `Bariatric Consultation and Customised Diet Plan`.

**Policy rules applied:**
- Global exclusion check: `"bariatric"` is in `EXCLUSION_KEYWORDS["bariatric"]`. Matched in diagnosis + treatment text → **REJECTED** at step 3 (before condition WP or line-item checks)

**System output:**
```json
{
  "decision": "REJECTED",
  "approved_amount": 0,
  "rejection_reasons": ["EXCLUDED_CONDITION"],
  "confidence_score": 0.95,
  "decision_reason": "Treatment is excluded under the policy. Bariatric surgery and obesity-related treatments are not covered."
}
```

**Match:** ✅ — `REJECTED`, reason `EXCLUDED_CONDITION`, confidence > 0.90.

---

## How to reproduce

### Interactive (recommended)

1. Start the stack: `docker-compose up -d`
2. Open `http://localhost:3000/tests`
3. Click **Run Test Suite** — all 12 cases run in-process (~300 ms) and results display with pass/fail badges, amounts, confidence bars, and expandable trace accordion.

### CLI (Docker)

```bash
docker-compose exec backend python3 -m pytest tests/test_cases/test_all_12_cases.py -v -s
```

Expected output:
```
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC001]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC002]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC003]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC004]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC005]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC006]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC007]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC008]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC009]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC010]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC011]
PASSED tests/test_cases/test_all_12_cases.py::test_case[TC012]

12 passed in 4.66s
```

### Local (no Docker)

```bash
cd backend
source .venv-core/bin/activate
python -m pytest tests/ -v
```

Expected: `29 passed` (includes all 12 case tests + 17 unit tests across 4 agent test files).
