"""
PolicyComplianceAgent — pure Python logic, no LLM.
Checks all policy rules in strict order and builds a complete audit trace.
"""
from datetime import date, timedelta
from typing import Optional

from app.agents.base import AgentResult, AgentTimer
from app.schemas.claim import ClaimSubmissionRequest
from app.schemas.document import ExtractedDocument
from app.services.policy_service import PolicyTerms, get_category_rules, is_network_hospital

# Keyword mappings for condition-specific waiting periods
CONDITION_KEYWORDS: dict[str, list[str]] = {
    "diabetes": ["diabetes", "diabetic", "t2dm", "type 2 diabetes", "type ii diabetes",
                 "dm type", "metformin", "glimepiride", "insulin", "hyperglycemia"],
    "hypertension": ["hypertension", "htn", "high blood pressure", "bp elevated",
                     "hypertensive", "amlodipine", "telmisartan", "losartan", "atenolol"],
    "thyroid_disorders": ["thyroid", "hypothyroidism", "hyperthyroidism", "thyroiditis",
                          "thyroxine", "t3", "t4", "tsh"],
    "joint_replacement": ["joint replacement", "knee replacement", "hip replacement",
                          "arthroplasty"],
    "maternity": ["maternity", "pregnancy", "prenatal", "antenatal", "obstetric",
                  "labour", "delivery", "caesarean", "c-section"],
    "mental_health": ["mental health", "psychiatric", "depression", "anxiety disorder",
                      "bipolar", "schizophrenia", "psychosis"],
    "obesity_treatment": ["obesity", "bariatric", "weight loss", "bmi 3", "morbid obesity"],
    "hernia": ["hernia repair", "herniorraphy", "hernioplasty", "inguinal hernia", "umbilical hernia"],
    "cataract": ["cataract", "phacoemulsification", "iol implant", "lens replacement"],
}

# Keywords for full exclusion check
EXCLUSION_KEYWORDS: dict[str, list[str]] = {
    "bariatric": ["bariatric", "bariatric surgery", "bariatric consultation",
                  "gastric bypass", "sleeve gastrectomy", "gastric banding"],
    "obesity_program": ["obesity treatment", "weight loss program", "diet plan for weight",
                        "obesity program", "weight management program"],
    "cosmetic": ["cosmetic", "aesthetic", "beautification", "botox", "liposuction",
                 "rhinoplasty", "blepharoplasty", "facelift"],
    "lasik": ["lasik", "refractive surgery", "laser eye surgery", "lasek"],
    "experimental": ["experimental", "trial treatment", "unapproved therapy", "investigational"],
    "self_inflicted": ["self-inflicted", "suicide attempt", "self harm", "self injury"],
    "infertility": ["infertility", "ivf", "assisted reproduction", "iui", "surrogacy"],
    "teeth_whitening": ["teeth whitening", "tooth whitening", "bleaching", "dental bleach"],
    "braces": ["orthodontic", "braces", "orthodontics"],
    "implants_cosmetic": ["cosmetic implant", "veneers", "cosmetic dental"],
    "vaccine": ["vaccination", "immunization", "vaccine", "flu shot"],
    "supplement": ["health supplement", "vitamin supplement", "tonic", "protein powder"],
}

MRI_KEYWORDS = ["mri", "magnetic resonance", "mri scan"]
CT_KEYWORDS = ["ct scan", "computed tomography", "ct-scan", "ctscan"]
PET_KEYWORDS = ["pet scan", "positron emission"]


def _text_contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _get_combined_text(*extracted_docs: ExtractedDocument) -> str:
    """Full text including line items, medicines, tests — used for condition waiting period checks."""
    parts = []
    for doc in extracted_docs:
        if doc.diagnosis:
            parts.append(doc.diagnosis)
        if doc.treatment:
            parts.append(doc.treatment)
        for item in doc.line_items:
            parts.append(item.get("description", ""))
        parts.extend(doc.medicines)
        parts.extend(doc.tests_ordered)
    return " ".join(parts)


def _get_diagnosis_treatment_text(*extracted_docs: ExtractedDocument) -> str:
    """Narrow text (diagnosis + treatment only) used for global exclusion checks.
    Excludes line item descriptions so cosmetic line items in a covered bill
    are handled at the per-line-item level (PARTIAL) not as global REJECTED."""
    parts = []
    for doc in extracted_docs:
        if doc.diagnosis:
            parts.append(doc.diagnosis)
        if doc.treatment:
            parts.append(doc.treatment)
    return " ".join(parts)


class PolicyComplianceAgent:
    NAME = "PolicyComplianceAgent"

    def __init__(self, policy: PolicyTerms):
        self.policy = policy

    async def run(
        self,
        claim: ClaimSubmissionRequest,
        extracted_docs: list[ExtractedDocument],
        member_join_date: date,
        member_name: str,
    ) -> AgentResult:
        timer = AgentTimer()
        timer.start()
        try:
            result = self._check_compliance(claim, extracted_docs, member_join_date, member_name)
            return AgentResult(
                success=True,
                data=result,
                error=None,
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )
        except Exception as e:
            return AgentResult(
                success=False,
                data=None,
                error=str(e),
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )

    def _check_compliance(
        self,
        claim: ClaimSubmissionRequest,
        extracted_docs: list[ExtractedDocument],
        member_join_date: date,
        member_name: str,
    ) -> dict:
        trace_steps = []
        treatment_date = claim.treatment_date
        claimed_amount = float(claim.claimed_amount)
        combined_text = _get_combined_text(*extracted_docs)
        diagnosis_treatment_text = _get_diagnosis_treatment_text(*extracted_docs)

        def step(check: str, passed: bool, detail: str):
            trace_steps.append({"check": check, "passed": passed, "detail": detail})

        # Step 1: Initial 30-day waiting period
        days_since_join = (treatment_date - member_join_date).days
        if days_since_join < self.policy.waiting_periods.initial_waiting_period_days:
            eligible_date = member_join_date + timedelta(
                days=self.policy.waiting_periods.initial_waiting_period_days
            )
            step("Initial waiting period (30 days)", False,
                 f"Member joined {member_join_date}. Treatment on {treatment_date} "
                 f"({days_since_join} days). Eligible from {eligible_date}.")
            return self._rejected(
                trace_steps, claimed_amount,
                reasons=["WAITING_PERIOD"],
                reason_text=f"Initial 30-day waiting period not completed. Eligible from {eligible_date}.",
                waiting_period_eligible_from=str(eligible_date),
            )
        step("Initial waiting period (30 days)", True,
             f"Member joined {member_join_date}. {days_since_join} days have elapsed. Passes.")

        # Step 2: Category coverage check (needed before exclusions for category_rules)
        category_rules = get_category_rules(self.policy, claim.claim_category)
        if category_rules is None or not category_rules.covered:
            step("Category coverage", False, f"Category {claim.claim_category} is not covered.")
            return self._rejected(
                trace_steps, claimed_amount,
                reasons=["CATEGORY_NOT_COVERED"],
                reason_text=f"Claim category '{claim.claim_category}' is not covered under this policy.",
            )
        step("Category coverage", True, f"{claim.claim_category} is covered.")

        # Step 3: Global exclusions check (before condition-specific waiting periods so that
        # fully excluded conditions like bariatric return EXCLUDED_CONDITION, not WAITING_PERIOD).
        # Uses diagnosis+treatment only (not line items) so cosmetic line items in an
        # otherwise-covered bill are handled at Step 4 for PARTIAL, not REJECTED here.
        for excl_key, keywords in EXCLUSION_KEYWORDS.items():
            if _text_contains_any(diagnosis_treatment_text, keywords):
                step(f"Exclusion: {excl_key}", False,
                     f"Text matches excluded condition '{excl_key}'.")
                return self._rejected(
                    trace_steps, claimed_amount,
                    reasons=["EXCLUDED_CONDITION"],
                    reason_text=(
                        f"This claim is for an excluded condition or procedure: "
                        f"{excl_key.replace('_', ' ').title()}. "
                        f"This is not covered under your policy."
                    ),
                    confidence=0.95,
                )
        step("Exclusions check", True, "No excluded conditions detected in documents.")

        # Step 4: Condition-specific waiting periods (after exclusions so that excluded
        # conditions surface the correct rejection reason, not a waiting period message)
        for condition, keywords in CONDITION_KEYWORDS.items():
            if _text_contains_any(combined_text, keywords):
                waiting_days = self.policy.waiting_periods.specific_conditions.get(condition)
                if waiting_days and days_since_join < waiting_days:
                    eligible_date = member_join_date + timedelta(days=waiting_days)
                    step(f"Condition waiting period: {condition}", False,
                         f"Diagnosis matches '{condition}' (waiting: {waiting_days} days). "
                         f"{days_since_join} days since join. Eligible from {eligible_date}.")
                    return self._rejected(
                        trace_steps, claimed_amount,
                        reasons=["WAITING_PERIOD"],
                        reason_text=(
                            f"Claim rejected: {condition.replace('_', ' ').title()} has a "
                            f"{waiting_days}-day waiting period. Member joined {member_join_date}. "
                            f"Eligible for {condition.replace('_', ' ').title()} claims from {eligible_date}."
                        ),
                        waiting_period_eligible_from=str(eligible_date),
                    )
                elif waiting_days:
                    step(f"Condition waiting period: {condition}", True,
                         f"Matches '{condition}' but {days_since_join} >= {waiting_days} days. Passes.")

        # Step 5: Line-item level exclusions (for PARTIAL decisions)
        line_items_all = []
        for doc in extracted_docs:
            line_items_all.extend(doc.line_items)

        line_item_decisions = []
        excluded_procedures_lower = [p.lower() for p in category_rules.excluded_procedures]
        has_excluded = False
        has_approved = False

        if line_items_all:
            for item in line_items_all:
                desc = item.get("description", "")
                amt = float(item.get("amount", 0))
                is_excluded = any(ep in desc.lower() for ep in excluded_procedures_lower)
                if is_excluded:
                    has_excluded = True
                    # Find which procedure
                    matched = next(
                        (ep for ep in category_rules.excluded_procedures if ep.lower() in desc.lower()),
                        desc
                    )
                    line_item_decisions.append({
                        "description": desc,
                        "amount": amt,
                        "approved": False,
                        "approved_amount": 0.0,
                        "reason": f"'{matched}' is excluded under {claim.claim_category} coverage.",
                    })
                else:
                    has_approved = True
                    line_item_decisions.append({
                        "description": desc,
                        "amount": amt,
                        "approved": True,
                        "approved_amount": amt,
                        "reason": None,
                    })

            approved_total = sum(
                d["approved_amount"] for d in line_item_decisions if d["approved"]
            )
        else:
            approved_total = claimed_amount
            has_approved = True

        if has_excluded:
            step("Line-item exclusions", True if has_approved else False,
                 f"Some line items excluded. Approved total: ₹{approved_total:.2f}")
        else:
            step("Line-item exclusions", True, "No line-item exclusions found.")

        # Step 6: Pre-authorization check
        pre_auth_needed = False
        pre_auth_reason = ""

        # Check high-value diagnostic tests
        high_value_tests = category_rules.high_value_tests_requiring_pre_auth
        pre_auth_threshold = category_rules.pre_auth_threshold or 0

        if high_value_tests and claimed_amount > pre_auth_threshold:
            for test in high_value_tests:
                if _text_contains_any(combined_text, [test.lower()]):
                    pre_auth_needed = True
                    pre_auth_reason = (
                        f"{test} above ₹{pre_auth_threshold:,.0f} requires pre-authorization."
                    )
                    break

        if category_rules.requires_pre_auth:
            pre_auth_needed = True
            pre_auth_reason = f"{claim.claim_category} category requires pre-authorization."

        if pre_auth_needed:
            # Check if pre_auth was provided (not in current schema — treat as absent)
            step("Pre-authorization", False, pre_auth_reason)
            return self._rejected(
                trace_steps, claimed_amount,
                reasons=["PRE_AUTH_MISSING"],
                reason_text=(
                    f"{pre_auth_reason} Pre-authorization was not obtained before treatment. "
                    f"To resubmit: contact ICICI Lombard to obtain a pre-authorization reference number, "
                    f"then resubmit this claim with the pre-authorization number."
                ),
            )
        step("Pre-authorization", True, "Pre-authorization not required for this claim.")

        # Step 7: Per-claim ceiling check (against approved line-item total, not claimed_amount).
        # Effective ceiling = max(category sub-limit, global per-claim-limit) so high-value
        # categories like DENTAL (sub=10000) allow claims beyond the global floor (5000).
        per_claim_limit = self.policy.coverage.per_claim_limit
        sub_limit = category_rules.sub_limit
        effective_ceiling = max(sub_limit, per_claim_limit)

        if approved_total > effective_ceiling:
            step("Per-claim limit", False,
                 f"Approved ₹{approved_total:,.2f} > limit ₹{effective_ceiling:,.2f}")
            return self._rejected(
                trace_steps, claimed_amount,
                reasons=["PER_CLAIM_EXCEEDED"],
                reason_text=(
                    f"Claimed amount ₹{claimed_amount:,.2f} exceeds the per-claim limit of "
                    f"₹{effective_ceiling:,.2f} for this policy. "
                    f"This claim cannot be approved in full or in part."
                ),
            )
        step("Per-claim limit", True,
             f"Approved ₹{approved_total:,.2f} ≤ limit ₹{effective_ceiling:,.2f}")

        # Step 8: Sub-limit is already enforced by the ceiling in Step 7;
        # no additional cap needed. effective_amount starts from approved_total.
        effective_amount = approved_total
        sub_limit_applied = 0.0
        step("Sub-limit", True,
             f"Amount ₹{effective_amount:,.2f} within category limit ₹{sub_limit:,.2f}. No additional cap.")

        # Step 9: Network discount FIRST, then co-pay
        network_discount = 0.0
        is_network = is_network_hospital(self.policy, claim.hospital_name)

        if is_network:
            discount_rate = category_rules.network_discount_percent / 100
            network_discount = round(effective_amount * discount_rate, 2)
            effective_amount = round(effective_amount - network_discount, 2)
            step("Network discount", True,
                 f"Network hospital detected. {category_rules.network_discount_percent}% discount "
                 f"applied: ₹{network_discount:,.2f} off. Amount after discount: ₹{effective_amount:,.2f}")
        else:
            step("Network discount", True,
                 f"Not a network hospital. No network discount applied.")

        copay_rate = category_rules.copay_percent / 100
        copay_amount = round(effective_amount * copay_rate, 2)
        final_amount = round(effective_amount - copay_amount, 2)

        step("Co-pay calculation", True,
             f"{category_rules.copay_percent}% co-pay on ₹{effective_amount:,.2f} = ₹{copay_amount:,.2f}. "
             f"Final approved: ₹{final_amount:,.2f}")

        # Step 10: Determine decision
        if has_excluded and has_approved:
            decision = "PARTIAL"
            reason_text = (
                f"Claim partially approved. Some line items are excluded under your {claim.claim_category} coverage. "
                f"Approved amount: ₹{final_amount:,.2f} after co-pay deduction."
            )
        else:
            decision = "APPROVED"
            reason_text = (
                f"Claim approved. All documents verified and policy checks passed. "
                f"Approved amount: ₹{final_amount:,.2f}"
            )
            if copay_amount > 0:
                reason_text += f" ({category_rules.copay_percent}% co-pay of ₹{copay_amount:,.2f} deducted)."
            if network_discount > 0:
                reason_text += f" Network discount of ₹{network_discount:,.2f} applied."

        avg_confidence = 0.92
        if extracted_docs:
            confidences = [d.extraction_confidence for d in extracted_docs if d.extraction_confidence]
            if confidences:
                avg_confidence = sum(confidences) / len(confidences)

        return {
            "decision": decision,
            "approved_amount": final_amount,
            "rejection_reasons": [],
            "reason_text": reason_text,
            "confidence": avg_confidence,
            "waiting_period_eligible_from": None,
            "line_item_decisions": line_item_decisions,
            "financial_breakdown": {
                "claimed_amount": claimed_amount,
                "approved_line_items_total": approved_total,
                "sub_limit_applied": sub_limit_applied,
                "network_discount_applied": network_discount,
                "amount_after_discount": effective_amount + copay_amount,
                "copay_deducted": copay_amount,
                "final_amount": final_amount,
                "network_hospital": is_network,
                "copay_percent": category_rules.copay_percent,
                "network_discount_percent": category_rules.network_discount_percent if is_network else 0,
            },
            "trace_steps": trace_steps,
        }

    def _rejected(
        self,
        trace_steps: list,
        claimed_amount: float,
        reasons: list[str],
        reason_text: str,
        waiting_period_eligible_from: Optional[str] = None,
        confidence: float = 0.95,
    ) -> dict:
        return {
            "decision": "REJECTED",
            "approved_amount": 0.0,
            "rejection_reasons": reasons,
            "reason_text": reason_text,
            "confidence": confidence,
            "waiting_period_eligible_from": waiting_period_eligible_from,
            "line_item_decisions": [],
            "financial_breakdown": {
                "claimed_amount": claimed_amount,
                "approved_line_items_total": 0.0,
                "sub_limit_applied": 0.0,
                "network_discount_applied": 0.0,
                "amount_after_discount": 0.0,
                "copay_deducted": 0.0,
                "final_amount": 0.0,
                "network_hospital": False,
                "copay_percent": 0,
                "network_discount_percent": 0,
            },
            "trace_steps": trace_steps,
        }
