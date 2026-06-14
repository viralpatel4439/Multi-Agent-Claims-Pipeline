import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class FamilyFloater(BaseModel):
    enabled: bool
    combined_limit: float
    covered_relationships: list[str]


class Coverage(BaseModel):
    sum_insured_per_employee: float
    annual_opd_limit: float
    per_claim_limit: float
    family_floater: FamilyFloater


class CategoryRules(BaseModel):
    sub_limit: float
    copay_percent: float = 0.0
    network_discount_percent: float = 0.0
    requires_prescription: bool = False
    requires_pre_auth: bool = False
    pre_auth_threshold: Optional[float] = None
    high_value_tests_requiring_pre_auth: list[str] = []
    covered: bool = True
    covered_procedures: list[str] = []
    excluded_procedures: list[str] = []
    covered_items: list[str] = []
    excluded_items: list[str] = []
    covered_systems: list[str] = []
    requires_dental_report: bool = False
    requires_registered_practitioner: bool = False
    max_sessions_per_year: Optional[int] = None
    branded_drug_copay_percent: float = 0.0
    generic_mandatory: bool = False


class WaitingPeriods(BaseModel):
    initial_waiting_period_days: int
    pre_existing_conditions_days: int
    specific_conditions: dict[str, int]


class Exclusions(BaseModel):
    conditions: list[str]
    dental_exclusions: list[str] = []
    vision_exclusions: list[str] = []


class FraudThresholds(BaseModel):
    same_day_claims_limit: int
    monthly_claims_limit: int
    high_value_claim_threshold: float
    auto_manual_review_above: float
    fraud_score_manual_review_threshold: float


class DocumentRequirements(BaseModel):
    required: list[str]
    optional: list[str] = []


class PolicyTerms(BaseModel):
    policy_id: str
    opd_categories: dict[str, CategoryRules]
    waiting_periods: WaitingPeriods
    exclusions: Exclusions
    pre_authorization: dict
    network_hospitals: list[str]
    submission_rules: dict
    document_requirements: dict[str, DocumentRequirements]
    fraud_thresholds: FraudThresholds
    coverage: Coverage


_policy_cache: Optional[PolicyTerms] = None


def clear_policy_cache():
    global _policy_cache
    _policy_cache = None


def load_policy(policy_file_path: str) -> PolicyTerms:
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache

    with open(policy_file_path) as f:
        data = json.load(f)

    _policy_cache = PolicyTerms(
        policy_id=data["policy_id"],
        opd_categories={k: CategoryRules(**v) for k, v in data["opd_categories"].items()},
        waiting_periods=WaitingPeriods(**data["waiting_periods"]),
        exclusions=Exclusions(**data["exclusions"]),
        pre_authorization=data["pre_authorization"],
        network_hospitals=data["network_hospitals"],
        submission_rules=data["submission_rules"],
        document_requirements={
            k: DocumentRequirements(**v) for k, v in data["document_requirements"].items()
        },
        fraud_thresholds=FraudThresholds(**data["fraud_thresholds"]),
        coverage=Coverage(**data["coverage"]),
    )
    return _policy_cache


def get_category_rules(policy: PolicyTerms, claim_category: str) -> Optional[CategoryRules]:
    return policy.opd_categories.get(claim_category.lower())


def is_network_hospital(policy: PolicyTerms, hospital_name: Optional[str]) -> bool:
    if not hospital_name:
        return False
    hospital_lower = hospital_name.lower()
    return any(nh.lower() in hospital_lower or hospital_lower in nh.lower()
               for nh in policy.network_hospitals)


def get_document_requirements(policy: PolicyTerms, claim_category: str) -> Optional[DocumentRequirements]:
    return policy.document_requirements.get(claim_category.upper())
