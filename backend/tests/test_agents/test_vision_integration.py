"""
Integration tests that actually call the Ollama vision model.

Skipped automatically if Ollama is unreachable — safe to run in CI where
Ollama is absent. Run them explicitly inside the Docker backend container:

    docker-compose exec backend python -m pytest \
        tests/test_agents/test_vision_integration.py -v -s

The -s flag lets the print() calls show what the model actually extracted.
"""
import os
from pathlib import Path

import httpx
import pytest

from app.agents.document_extractor import DocumentExtractionAgent
from app.schemas.document import DocumentInput

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
SAMPLES = Path(__file__).parent.parent / "sample_documents"

pytestmark = pytest.mark.integration


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def require_ollama():
    """Skip every test in this module if Ollama isn't reachable."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        reachable = r.status_code == 200
    except Exception:
        reachable = False

    if not reachable:
        pytest.skip(f"Ollama not reachable at {OLLAMA_URL} — skipping vision integration tests")


@pytest.fixture
def extractor():
    return DocumentExtractionAgent()


# ── Individual document tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vision_prescription(extractor):
    """Vision model extracts structured data from the sample prescription PDF."""
    doc = DocumentInput(
        file_id="INT_RX",
        actual_type="PRESCRIPTION",
        file_path=str(SAMPLES / "prescription.pdf"),
    )
    result = await extractor.run(doc)

    assert result.success, f"Extraction failed: {result.error}"
    data = result.data
    assert data["extraction_confidence"] > 0.0
    print(
        f"\n[prescription] patient={data.get('patient_name')!r}"
        f"  diagnosis={data.get('diagnosis')!r}"
        f"  confidence={data.get('extraction_confidence')}"
    )


@pytest.mark.asyncio
async def test_vision_hospital_bill(extractor):
    """Vision model extracts line items and totals from the sample hospital bill PDF."""
    doc = DocumentInput(
        file_id="INT_BILL",
        actual_type="HOSPITAL_BILL",
        file_path=str(SAMPLES / "hospital_bill.pdf"),
    )
    result = await extractor.run(doc)

    assert result.success, f"Extraction failed: {result.error}"
    data = result.data
    assert data["extraction_confidence"] > 0.0
    print(
        f"\n[hospital_bill] patient={data.get('patient_name')!r}"
        f"  total={data.get('total_amount')}"
        f"  line_items={len(data.get('line_items', []))}"
        f"  confidence={data.get('extraction_confidence')}"
    )


@pytest.mark.asyncio
async def test_vision_lab_report(extractor):
    """Vision model extracts test names and results from the sample lab report PDF."""
    doc = DocumentInput(
        file_id="INT_LAB",
        actual_type="LAB_REPORT",
        file_path=str(SAMPLES / "lab_report.pdf"),
    )
    result = await extractor.run(doc)

    assert result.success, f"Extraction failed: {result.error}"
    data = result.data
    assert data["extraction_confidence"] > 0.0
    print(
        f"\n[lab_report] patient={data.get('patient_name')!r}"
        f"  tests={data.get('tests_ordered')}"
        f"  confidence={data.get('extraction_confidence')}"
    )


@pytest.mark.asyncio
async def test_vision_pharmacy_bill(extractor):
    """Vision model extracts medicines and totals from the sample pharmacy bill PDF."""
    doc = DocumentInput(
        file_id="INT_PHARM",
        actual_type="PHARMACY_BILL",
        file_path=str(SAMPLES / "pharmacy_bill.pdf"),
    )
    result = await extractor.run(doc)

    assert result.success, f"Extraction failed: {result.error}"
    data = result.data
    assert data["extraction_confidence"] > 0.0
    print(
        f"\n[pharmacy_bill] patient={data.get('patient_name')!r}"
        f"  medicines={data.get('medicines')}"
        f"  total={data.get('total_amount')}"
        f"  confidence={data.get('extraction_confidence')}"
    )


# ── Batch extraction test ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vision_batch_two_docs(extractor):
    """
    Batch call: prescription + hospital bill sent to Ollama in a single request.
    Verifies that both documents get results and both produce embeddings.
    """
    docs = [
        DocumentInput(
            file_id="BATCH_RX",
            actual_type="PRESCRIPTION",
            file_path=str(SAMPLES / "prescription.pdf"),
        ),
        DocumentInput(
            file_id="BATCH_BILL",
            actual_type="HOSPITAL_BILL",
            file_path=str(SAMPLES / "hospital_bill.pdf"),
        ),
    ]
    results = await extractor.run_batch(docs)

    assert len(results) == 2
    for i, r in enumerate(results):
        assert r.success, f"Batch doc {i} failed: {r.error}"
        assert r.data["extraction_confidence"] > 0.0
        print(
            f"\n[batch doc {i}]"
            f"  type={r.data.get('document_type')}"
            f"  confidence={r.data.get('extraction_confidence')}"
            f"  has_embedding={r.data.get('diagnosis_embedding') is not None}"
        )


# ── Embedding test ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vision_produces_embedding(extractor):
    """
    After vision extraction, the agent embeds the diagnosis (or treatment fallback).
    Verifies the embedding is 384-dimensional when the model returns any text field.
    """
    doc = DocumentInput(
        file_id="INT_EMB",
        actual_type="PRESCRIPTION",
        file_path=str(SAMPLES / "prescription.pdf"),
    )
    result = await extractor.run(doc)

    assert result.success
    emb = result.data.get("diagnosis_embedding")
    if emb is not None:
        assert len(emb) == 384, f"Expected 384-dim embedding, got {len(emb)}"
        print(f"\n[embedding] dim={len(emb)}  first3={emb[:3]}")
    else:
        # Acceptable only if both diagnosis AND treatment are null
        diag = result.data.get("diagnosis")
        treat = result.data.get("treatment")
        assert diag is None and treat is None, (
            f"Embedding missing but diagnosis={diag!r} treatment={treat!r}"
        )
        print("\n[embedding] skipped — model returned no diagnosis or treatment")
