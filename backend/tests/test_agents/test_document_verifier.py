import pytest
from app.agents.document_verifier import DocumentVerificationAgent
from app.schemas.document import DocumentInput


@pytest.mark.asyncio
async def test_tc001_wrong_doc_type(policy):
    """TC001: Two PRESCRIPTIONs for CONSULTATION — HOSPITAL_BILL missing."""
    agent = DocumentVerificationAgent(policy)
    docs = [
        DocumentInput(file_id="F001", file_name="dr_sharma_prescription.jpg", actual_type="PRESCRIPTION"),
        DocumentInput(file_id="F002", file_name="another_prescription.jpg", actual_type="PRESCRIPTION"),
    ]
    result = await agent.run(docs, "CONSULTATION", "EMP001")

    assert result.success
    assert not result.data["valid"]
    issues = result.data["issues"]
    assert len(issues) > 0
    assert any(i["issue_type"] == "WRONG_DOC_TYPE" for i in issues)
    # Message must name HOSPITAL_BILL and what was uploaded
    msg = issues[0]["message"]
    assert "HOSPITAL_BILL" in msg
    assert "PRESCRIPTION" in msg


@pytest.mark.asyncio
async def test_tc002_unreadable_document(policy):
    """TC002: Valid types but PHARMACY_BILL is UNREADABLE."""
    agent = DocumentVerificationAgent(policy)
    docs = [
        DocumentInput(file_id="F003", file_name="prescription.jpg", actual_type="PRESCRIPTION", quality="GOOD"),
        DocumentInput(file_id="F004", file_name="blurry_bill.jpg", actual_type="PHARMACY_BILL", quality="UNREADABLE"),
    ]
    result = await agent.run(docs, "PHARMACY", "EMP004")

    assert result.success
    assert not result.data["valid"]
    issues = result.data["issues"]
    assert any(i["issue_type"] == "UNREADABLE" for i in issues)
    # Must NOT say "rejected" — must say re-upload
    unreadable_issue = next(i for i in issues if i["issue_type"] == "UNREADABLE")
    assert "re-upload" in unreadable_issue["message"].lower() or "upload" in unreadable_issue["message"].lower()


@pytest.mark.asyncio
async def test_tc003_patient_mismatch(policy):
    """TC003: Different patient names on prescription and bill."""
    agent = DocumentVerificationAgent(policy)
    docs = [
        DocumentInput(file_id="F005", file_name="prescription_rajesh.jpg", actual_type="PRESCRIPTION",
                      patient_name_on_doc="Rajesh Kumar"),
        DocumentInput(file_id="F006", file_name="bill_arjun.jpg", actual_type="HOSPITAL_BILL",
                      patient_name_on_doc="Arjun Mehta"),
    ]
    result = await agent.run(docs, "CONSULTATION", "EMP001")

    assert result.success
    assert not result.data["valid"]
    issues = result.data["issues"]
    assert any(i["issue_type"] == "PATIENT_MISMATCH" for i in issues)
    mismatch = next(i for i in issues if i["issue_type"] == "PATIENT_MISMATCH")
    assert "Rajesh Kumar" in mismatch["message"]
    assert "Arjun Mehta" in mismatch["message"]


@pytest.mark.asyncio
async def test_valid_consultation_docs(policy):
    """Valid CONSULTATION with correct doc types passes verification."""
    agent = DocumentVerificationAgent(policy)
    docs = [
        DocumentInput(file_id="F007", actual_type="PRESCRIPTION", quality="GOOD"),
        DocumentInput(file_id="F008", actual_type="HOSPITAL_BILL", quality="GOOD"),
    ]
    result = await agent.run(docs, "CONSULTATION", "EMP001")

    assert result.success
    assert result.data["valid"]
    assert result.data["issues"] == []


@pytest.mark.asyncio
async def test_valid_pharmacy_docs(policy):
    """Valid PHARMACY with PRESCRIPTION + PHARMACY_BILL."""
    agent = DocumentVerificationAgent(policy)
    docs = [
        DocumentInput(file_id="F009", actual_type="PRESCRIPTION"),
        DocumentInput(file_id="F010", actual_type="PHARMACY_BILL"),
    ]
    result = await agent.run(docs, "PHARMACY", "EMP002")

    assert result.success
    assert result.data["valid"]
