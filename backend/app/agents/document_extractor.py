"""
DocumentExtractionAgent — extracts structured data from medical documents.
Supports two modes:
  - Structured mode: content dict provided (test cases / API with JSON)
  - LLM mode: calls NVIDIA NIM when NVIDIA_API_KEY is set and content is provided
"""
import json
import os
from typing import Optional

from app.agents.base import AgentResult, AgentTimer
from app.schemas.document import DocumentInput, ExtractedDocument
from app.services import embedding_service

EXTRACTION_PROMPT = """You are extracting structured data from an Indian medical document.

Document content:
{content}

Extract ALL available fields and return ONLY valid JSON (no markdown, no explanation):
{{
  "patient_name": "string or null",
  "doctor_name": "string or null",
  "doctor_registration": "string or null",
  "diagnosis": "string or null",
  "treatment": "string or null",
  "date": "YYYY-MM-DD string or null",
  "hospital_name": "string or null",
  "medicines": ["list of medicine strings"],
  "tests_ordered": ["list of test name strings"],
  "line_items": [
    {{"description": "string", "amount": number}}
  ],
  "total_amount": "number or null",
  "extraction_confidence": "number 0.0-1.0",
  "fields_low_confidence": ["list of field names you are unsure about"]
}}

For extraction_confidence: use 0.9+ for clear structured data, 0.6-0.9 for partially clear, below 0.6 for poor quality.
"""

NVIDIA_MODEL = "minimaxai/minimax-m3"


class DocumentExtractionAgent:
    NAME = "DocumentExtractionAgent"

    def __init__(self):
        # client is non-None when NVIDIA key is available; tests set it to None to force fallback
        self.client = NVIDIA_MODEL if os.environ.get("NVIDIA_API_KEY") else None

    async def run(
        self,
        document: DocumentInput,
        simulate_failure: bool = False,
    ) -> AgentResult:
        timer = AgentTimer()
        timer.start()
        try:
            if simulate_failure:
                raise RuntimeError("Simulated extraction failure for TC011 testing")

            extracted = await self._extract(document)

            if extracted.diagnosis:
                extracted.diagnosis_embedding = embedding_service.embed_text(extracted.diagnosis)

            return AgentResult(
                success=True,
                data=extracted.model_dump(),
                error=None,
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )

        except Exception as e:
            return AgentResult(
                success=False,
                data={
                    "document_type": document.actual_type,
                    "extraction_confidence": 0.0,
                    "fields_low_confidence": ["all"],
                    "error_message": str(e),
                },
                error=str(e),
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )

    async def _extract(self, document: DocumentInput) -> ExtractedDocument:
        if document.content:
            return await self._extract_from_structured_content(document)
        return self._extract_passthrough(document)

    async def _extract_from_structured_content(self, document: DocumentInput) -> ExtractedDocument:
        if self.client is None:
            return self._extract_from_dict(document)

        try:
            from app.services.nvidia_service import get_completion
            content_str = json.dumps(document.content, indent=2)
            prompt = EXTRACTION_PROMPT.format(content=content_str)
            raw = await get_completion(self.client, prompt)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return self._build_extracted(document.actual_type, parsed)
        except Exception:
            return self._extract_from_dict(document)

    def _extract_from_dict(self, document: DocumentInput) -> ExtractedDocument:
        """Direct extraction from structured content dict — no LLM call."""
        c = document.content or {}
        line_items = [
            {"description": item.get("description", ""), "amount": item.get("amount", 0)}
            for item in c.get("line_items", [])
        ]
        return ExtractedDocument(
            document_type=document.actual_type,
            patient_name=c.get("patient_name"),
            doctor_name=c.get("doctor_name"),
            doctor_registration=c.get("doctor_registration"),
            diagnosis=c.get("diagnosis"),
            treatment=c.get("treatment"),
            date=str(c.get("date")) if c.get("date") else None,
            hospital_name=c.get("hospital_name"),
            medicines=c.get("medicines", []),
            tests_ordered=c.get("tests_ordered", []),
            line_items=line_items,
            amounts=line_items.copy(),
            total_amount=c.get("total"),
            extraction_confidence=0.95,
            fields_low_confidence=[],
        )

    def _build_extracted(self, doc_type: str, parsed: dict) -> ExtractedDocument:
        line_items = parsed.get("line_items", [])
        return ExtractedDocument(
            document_type=doc_type,
            patient_name=parsed.get("patient_name"),
            doctor_name=parsed.get("doctor_name"),
            doctor_registration=parsed.get("doctor_registration"),
            diagnosis=parsed.get("diagnosis"),
            treatment=parsed.get("treatment"),
            date=parsed.get("date"),
            hospital_name=parsed.get("hospital_name"),
            medicines=parsed.get("medicines", []),
            tests_ordered=parsed.get("tests_ordered", []),
            line_items=line_items,
            amounts=line_items,
            total_amount=parsed.get("total_amount"),
            extraction_confidence=float(parsed.get("extraction_confidence", 0.9)),
            fields_low_confidence=parsed.get("fields_low_confidence", []),
        )

    def _extract_passthrough(self, document: DocumentInput) -> ExtractedDocument:
        """Minimal extraction when no content is available."""
        return ExtractedDocument(
            document_type=document.actual_type,
            extraction_confidence=0.3,
            fields_low_confidence=["all"],
        )
