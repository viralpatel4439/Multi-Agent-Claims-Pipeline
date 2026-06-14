import pytest
from app.agents.document_extractor import DocumentExtractionAgent
from app.schemas.document import DocumentInput


@pytest.fixture
def extractor():
    return DocumentExtractionAgent()


@pytest.mark.asyncio
async def test_extracts_from_structured_content(extractor, monkeypatch):
    """Extraction from structured content dict works without LLM."""
    # Disable LLM client to force fallback path
    extractor.client = None

    doc = DocumentInput(
        file_id="F001",
        actual_type="PRESCRIPTION",
        content={
            "patient_name": "Rajesh Kumar",
            "doctor_name": "Dr. Arun Sharma",
            "diagnosis": "Viral Fever",
            "total": 1500,
            "line_items": [{"description": "Consultation Fee", "amount": 1000}],
        }
    )
    result = await extractor.run(doc)

    assert result.success
    assert result.data["patient_name"] == "Rajesh Kumar"
    assert result.data["diagnosis"] == "Viral Fever"
    assert result.data["extraction_confidence"] >= 0.9


@pytest.mark.asyncio
async def test_simulates_failure_tc011(extractor):
    """TC011: simulate_failure=True causes graceful failure."""
    doc = DocumentInput(file_id="F021", actual_type="PRESCRIPTION", content={"diagnosis": "Chronic Joint Pain"})
    result = await extractor.run(doc, simulate_failure=True)

    assert not result.success
    assert result.error is not None
    assert "Simulated" in result.error


@pytest.mark.asyncio
async def test_empty_doc_returns_passthrough(extractor):
    """Document with no content returns low-confidence passthrough."""
    extractor.client = None
    doc = DocumentInput(file_id="F999", actual_type="HOSPITAL_BILL")
    result = await extractor.run(doc)

    assert result.success
    assert result.data["extraction_confidence"] <= 0.3
