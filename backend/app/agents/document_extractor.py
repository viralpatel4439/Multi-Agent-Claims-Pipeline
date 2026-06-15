"""
DocumentExtractionAgent — extracts structured data from medical documents.

Three extraction modes (in priority order):
  1. Vision mode:      file_path provided → PyMuPDF renders pages → Ollama vision model
  2. Structured mode:  content dict provided → direct dict mapping (no LLM)
  3. Passthrough:      neither provided → low-confidence empty result
"""
import json
from pathlib import Path
from typing import Optional

from app.agents.base import AgentResult, AgentTimer
from app.schemas.document import DocumentInput, ExtractedDocument
from app.services import embedding_service

VISION_EXTRACTION_PROMPT = """You are analyzing an Indian medical document image.
It may be a prescription, hospital bill, lab report, or pharmacy bill.
The image may have handwriting, rubber stamps, phone-photo quality, or mixed languages.

Extract ALL visible fields and return ONLY valid JSON (no markdown, no explanation):
{
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
    {"description": "string", "amount": number}
  ],
  "total_amount": "number or null",
  "extraction_confidence": "number 0.0-1.0",
  "fields_low_confidence": ["field names you are unsure about due to image quality"]
}

Rules:
- If a field is unreadable (handwriting, stamp, blur), set null and add to fields_low_confidence.
- For extraction_confidence: 0.9+ clear image, 0.6-0.9 partial issues, below 0.6 poor quality.
- Expand shorthand: HTN=Hypertension, T2DM=Type 2 Diabetes, URI=Upper Respiratory Infection.
- For multi-item bills, capture every line item in line_items."""


class DocumentExtractionAgent:
    NAME = "DocumentExtractionAgent"

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
        if document.file_path:
            return await self._extract_from_file(document)
        if document.content:
            return await self._extract_from_structured_content(document)
        return self._extract_passthrough(document)

    # ── Vision path (file upload) ──────────────────────────────────────────────

    async def _extract_from_file(self, document: DocumentInput) -> ExtractedDocument:
        from app.services.ollama_service import extract_from_image_bytes

        path = Path(document.file_path)
        pages = self._file_to_image_pages(path)

        page_results = []
        for page_bytes in pages:
            raw = await extract_from_image_bytes(page_bytes, VISION_EXTRACTION_PROMPT)
            parsed = self._parse_json_safe(raw)
            if parsed:
                page_results.append(parsed)

        if not page_results:
            return self._extract_passthrough(document)

        merged = self._merge_page_results(page_results)
        return self._build_extracted(document.actual_type, merged)

    def _file_to_image_pages(self, path: Path) -> list[bytes]:
        if path.suffix.lower() == ".pdf":
            return self._pdf_to_images(path)
        return [path.read_bytes()]

    def _pdf_to_images(self, path: Path) -> list[bytes]:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        return [page.get_pixmap(dpi=200).tobytes("png") for page in doc]

    def _merge_page_results(self, results: list[dict]) -> dict:
        if len(results) == 1:
            return results[0]

        merged = results[0].copy()
        for r in results[1:]:
            # Accumulate list fields across pages
            for key in ("line_items", "medicines", "tests_ordered", "fields_low_confidence"):
                merged[key] = merged.get(key, []) + r.get(key, [])

            # Fill nulls from subsequent pages
            for key in ("patient_name", "doctor_name", "doctor_registration",
                        "diagnosis", "treatment", "date", "hospital_name", "total_amount"):
                if merged.get(key) is None and r.get(key) is not None:
                    merged[key] = r[key]

            # Take the minimum confidence across pages
            merged["extraction_confidence"] = min(
                merged.get("extraction_confidence", 0.9),
                r.get("extraction_confidence", 0.9),
            )

        return merged

    # ── Structured content path (test cases / API with JSON body) ─────────────

    async def _extract_from_structured_content(self, document: DocumentInput) -> ExtractedDocument:
        return self._extract_from_dict(document)

    def _extract_from_dict(self, document: DocumentInput) -> ExtractedDocument:
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

    # ── Shared helpers ─────────────────────────────────────────────────────────

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

    def _parse_json_safe(self, raw: str) -> Optional[dict]:
        try:
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError):
            return None

    def _extract_passthrough(self, document: DocumentInput) -> ExtractedDocument:
        return ExtractedDocument(
            document_type=document.actual_type,
            extraction_confidence=0.3,
            fields_low_confidence=["all"],
        )
