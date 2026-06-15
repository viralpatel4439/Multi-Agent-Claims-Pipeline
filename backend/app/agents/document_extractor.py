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

SINGLE_DOC_PROMPT = """You are analyzing an Indian medical document image.
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
  "line_items": [{"description": "string", "amount": number}],
  "total_amount": "number or null",
  "extraction_confidence": "number 0.0-1.0",
  "fields_low_confidence": ["field names you are unsure about due to image quality"]
}

Rules:
- If a field is unreadable (handwriting, stamp, blur), set null and add to fields_low_confidence.
- For extraction_confidence: 0.9+ clear image, 0.6-0.9 partial issues, below 0.6 poor quality.
- Expand shorthand: HTN=Hypertension, T2DM=Type 2 Diabetes, URI=Upper Respiratory Infection.
- For multi-item bills, capture every line item in line_items."""


def _batch_prompt(n: int, doc_types: list[str]) -> str:
    labels = "\n".join(f"- Image {i+1}: {doc_types[i]}" for i in range(n))
    schema = """{
  "patient_name": "string or null",
  "doctor_name": "string or null",
  "doctor_registration": "string or null",
  "diagnosis": "string or null",
  "treatment": "string or null",
  "date": "YYYY-MM-DD string or null",
  "hospital_name": "string or null",
  "medicines": ["list of medicine strings"],
  "tests_ordered": ["list of test name strings"],
  "line_items": [{"description": "string", "amount": number}],
  "total_amount": "number or null",
  "extraction_confidence": "number 0.0-1.0",
  "fields_low_confidence": ["field names you are unsure about"]
}"""
    return f"""You are analyzing {n} Indian medical document images provided in order.
{labels}

Extract ALL visible fields from EACH image and return ONLY a valid JSON array with exactly {n} objects (no markdown):
[
  {schema},
  ... (one object per image, same order)
]

Rules:
- If a field is unreadable, set null and add to fields_low_confidence.
- extraction_confidence: 0.9+ clear, 0.6-0.9 partial issues, below 0.6 poor quality.
- Expand shorthand: HTN=Hypertension, T2DM=Type 2 Diabetes, URI=Upper Respiratory Infection.
- Capture every line item for bills."""


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

    async def run_batch(
        self,
        documents: list[DocumentInput],
    ) -> list[AgentResult]:
        """
        Extract all documents in a SINGLE Ollama call.
        Documents without a file_path fall back to structured/passthrough extraction
        and are excluded from the vision batch.
        """
        from app.services.ollama_service import extract_from_image_batch

        timer = AgentTimer()
        timer.start()

        vision_indices: list[int] = []
        all_images: list[bytes] = []
        doc_types: list[str] = []

        import logging as _log
        _logger = _log.getLogger(__name__)

        for i, doc in enumerate(documents):
            if doc.file_path:
                try:
                    pages = self._compress_for_llm(Path(doc.file_path))
                except Exception as compress_err:
                    _logger.warning("[Compress] skipping %s (file_id=%s): %s",
                                    doc.file_path, doc.file_id, compress_err)
                    pages = []
                # Use only the first page per document in the batch call to keep token count low.
                if pages:
                    all_images.append(pages[0])
                    doc_types.append(doc.actual_type)
                    vision_indices.append(i)

        # Batch vision call
        batch_parsed: list[Optional[dict]] = [None] * len(vision_indices)
        if all_images:
            try:
                if len(all_images) == 1:
                    raw = await extract_from_image_batch(all_images, SINGLE_DOC_PROMPT)
                    parsed = self._parse_json_safe(raw)
                    batch_parsed[0] = parsed
                else:
                    raw = await extract_from_image_batch(all_images, _batch_prompt(len(all_images), doc_types))
                    parsed_list = self._parse_json_array_safe(raw)
                    for k, p in enumerate(parsed_list[:len(vision_indices)]):
                        batch_parsed[k] = p
            except Exception as e:
                # Mark all vision docs as failed
                batch_parsed = [None] * len(vision_indices)
                import logging
                logging.getLogger(__name__).error("[Ollama batch] %s", e)

        # Build AgentResult per document
        results: list[AgentResult] = []
        vision_cursor = 0
        elapsed = timer.elapsed_ms()

        for i, doc in enumerate(documents):
            try:
                if doc.file_path and i in vision_indices:
                    parsed = batch_parsed[vision_cursor]
                    vision_cursor += 1
                    if parsed:
                        extracted = self._build_extracted(doc.actual_type, parsed)
                    else:
                        extracted = self._extract_passthrough(doc)
                elif doc.content:
                    extracted = self._extract_from_dict(doc)
                else:
                    extracted = self._extract_passthrough(doc)

                if extracted.diagnosis:
                    extracted.diagnosis_embedding = embedding_service.embed_text(extracted.diagnosis)

                results.append(AgentResult(
                    success=True,
                    data=extracted.model_dump(),
                    error=None,
                    agent_name=self.NAME,
                    processing_time_ms=elapsed,
                ))
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).error(
                    "[run_batch] doc %s (file_id=%s) failed: %s",
                    i, doc.file_id, e, exc_info=True,
                )
                results.append(AgentResult(
                    success=False,
                    data={"document_type": doc.actual_type, "extraction_confidence": 0.0, "fields_low_confidence": ["all"], "error_message": str(e)},
                    error=str(e),
                    agent_name=self.NAME,
                    processing_time_ms=elapsed,
                ))

        return results

    # ── Vision path (file upload) ──────────────────────────────────────────────

    async def _extract_from_file(self, document: DocumentInput) -> ExtractedDocument:
        from app.services.ollama_service import extract_from_image_batch

        path = Path(document.file_path)
        pages = self._compress_for_llm(path)

        page_results = []
        for page_bytes in pages:
            raw = await extract_from_image_batch([page_bytes], SINGLE_DOC_PROMPT)
            parsed = self._parse_json_safe(raw)
            if parsed:
                page_results.append(parsed)

        if not page_results:
            return self._extract_passthrough(document)

        merged = self._merge_page_results(page_results)
        return self._build_extracted(document.actual_type, merged)

    def _compress_for_llm(self, path: Path) -> list[bytes]:
        """
        Read the ORIGINAL stored file and return compressed JPEG bytes for LLM.
        Nothing is written to disk — compression is in-memory only.

        PDF  → each page rendered at 100 DPI as JPEG (vs 200 DPI PNG = 8× smaller)
        Image (PNG / JPG / JPEG / WEBP) → resized to max 1024 px, JPEG quality 70

        Used on both the first pipeline run and every rerun.
        """
        import io
        import logging
        log = logging.getLogger(__name__)

        suffix = path.suffix.lower()
        original_size = path.stat().st_size

        if suffix == ".pdf":
            import fitz
            doc = fitz.open(str(path))
            pages = [page.get_pixmap(dpi=100).tobytes("jpeg") for page in doc]
            compressed_total = sum(len(p) for p in pages)
            log.info("[Compress] %s  PDF %d pages  %d B → %d B (%.0f%%)",
                     path.name, len(pages), original_size, compressed_total,
                     100 * compressed_total / max(original_size, 1))
            return pages

        # Image file: PNG, JPG, JPEG, WEBP, etc.
        from PIL import Image
        raw = path.read_bytes()
        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        max_px = 1024
        if max(img.size) > max_px:
            ratio = max_px / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=True)
        compressed = buf.getvalue()
        log.info("[Compress] %s  %s %dx%d  %d B → %d B (%.0f%%)",
                 path.name, suffix.upper(), img.width, img.height,
                 original_size, len(compressed),
                 100 * len(compressed) / max(original_size, 1))
        return [compressed]

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
            patient_name=self._coerce_str(c.get("patient_name")),
            doctor_name=self._coerce_str(c.get("doctor_name")),
            doctor_registration=self._coerce_str(c.get("doctor_registration")),
            diagnosis=self._coerce_str(c.get("diagnosis")),
            treatment=self._coerce_str(c.get("treatment")),
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

    @staticmethod
    def _coerce_str(value) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, list):
            return "; ".join(str(v) for v in value if v)
        return str(value)

    def _build_extracted(self, doc_type: str, parsed: dict) -> ExtractedDocument:
        line_items = parsed.get("line_items", [])
        return ExtractedDocument(
            document_type=doc_type,
            patient_name=self._coerce_str(parsed.get("patient_name")),
            doctor_name=self._coerce_str(parsed.get("doctor_name")),
            doctor_registration=self._coerce_str(parsed.get("doctor_registration")),
            diagnosis=self._coerce_str(parsed.get("diagnosis")),
            treatment=self._coerce_str(parsed.get("treatment")),
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

    def _parse_json_array_safe(self, raw: str) -> list[dict]:
        try:
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw.strip())
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
        except (json.JSONDecodeError, IndexError):
            pass
        return []

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
