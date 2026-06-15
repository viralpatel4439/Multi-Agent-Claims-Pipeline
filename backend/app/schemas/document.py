from typing import Optional
from pydantic import BaseModel, Field


class DocumentInput(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    actual_type: str
    quality: Optional[str] = "GOOD"
    content: Optional[dict] = None
    file_path: Optional[str] = None  # absolute path to uploaded PDF or image
    patient_name_on_doc: Optional[str] = None


class ExtractedDocument(BaseModel):
    document_type: str
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    diagnosis: Optional[str] = None
    diagnosis_embedding: Optional[list[float]] = None
    treatment: Optional[str] = None
    date: Optional[str] = None
    amounts: list[dict] = Field(default_factory=list)
    total_amount: Optional[float] = None
    line_items: list[dict] = Field(default_factory=list)
    extraction_confidence: float = 1.0
    fields_low_confidence: list[str] = Field(default_factory=list)
    tests_ordered: list[str] = Field(default_factory=list)
    hospital_name: Optional[str] = None
    medicines: list[str] = Field(default_factory=list)
