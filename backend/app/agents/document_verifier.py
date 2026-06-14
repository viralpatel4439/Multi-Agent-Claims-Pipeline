"""
DocumentVerificationAgent — pure rule-based, no LLM.
Catches document type mismatches, unreadable docs, and patient name mismatches
BEFORE the claim enters the async pipeline.
"""
from typing import Optional

from app.agents.base import AgentResult, AgentTimer
from app.schemas.document import DocumentInput
from app.services.policy_service import PolicyTerms, get_document_requirements


class DocumentVerificationAgent:
    NAME = "DocumentVerificationAgent"

    def __init__(self, policy: PolicyTerms):
        self.policy = policy

    async def run(
        self,
        documents: list[DocumentInput],
        claim_category: str,
        member_id: str,
    ) -> AgentResult:
        timer = AgentTimer()
        timer.start()
        try:
            issues = []

            # 1. Wrong document type check
            doc_requirements = get_document_requirements(self.policy, claim_category)
            if doc_requirements:
                submitted_types = [doc.actual_type for doc in documents]
                submitted_type_counts: dict[str, int] = {}
                for t in submitted_types:
                    submitted_type_counts[t] = submitted_type_counts.get(t, 0) + 1

                missing_required = []
                for required_type in doc_requirements.required:
                    if required_type not in submitted_types:
                        missing_required.append(required_type)

                if missing_required:
                    submitted_summary = ", ".join(submitted_types) if submitted_types else "no documents"
                    for missing_type in missing_required:
                        issues.append({
                            "issue_type": "WRONG_DOC_TYPE",
                            "file_id": None,
                            "message": (
                                f"Document type {missing_type} is required for {claim_category} claims. "
                                f"You uploaded: {submitted_summary}. "
                                f"Please provide a {missing_type} document."
                            ),
                        })

            # 2. Unreadable document check
            for doc in documents:
                if doc.quality and doc.quality.upper() == "UNREADABLE":
                    issues.append({
                        "issue_type": "UNREADABLE",
                        "file_id": doc.file_id,
                        "message": (
                            f"Document '{doc.file_name or doc.file_id}' (type: {doc.actual_type}) "
                            f"cannot be read — the image is too blurry or low quality. "
                            f"Please re-upload a clear photo or scan of this document."
                        ),
                    })

            # 3. Patient name mismatch check
            named_docs = [
                doc for doc in documents
                if doc.patient_name_on_doc and doc.patient_name_on_doc.strip()
            ]
            if named_docs:
                unique_names = list({doc.patient_name_on_doc.strip().lower() for doc in named_docs})
                if len(unique_names) > 1:
                    name_details = "; ".join(
                        f"'{doc.file_name or doc.file_id}' (type: {doc.actual_type}) — patient name: '{doc.patient_name_on_doc}'"
                        for doc in named_docs
                    )
                    issues.append({
                        "issue_type": "PATIENT_MISMATCH",
                        "file_id": None,
                        "message": (
                            f"The documents you uploaded belong to different patients. "
                            f"All documents for a single claim must be for the same patient. "
                            f"Details: {name_details}"
                        ),
                    })

            is_valid = len(issues) == 0
            return AgentResult(
                success=True,
                data={"valid": is_valid, "issues": issues},
                error=None,
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )

        except Exception as e:
            return AgentResult(
                success=False,
                data={"valid": False, "issues": []},
                error=str(e),
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )
