"""
Generate sample Indian medical documents as PDFs for pipeline testing.

Run from repo root:
    pip install fpdf2
    python backend/tests/sample_documents/generate.py

Produces four files in this directory:
    prescription.pdf
    hospital_bill.pdf
    lab_report.pdf
    pharmacy_bill.pdf
"""
from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).parent


def _divider(pdf: FPDF) -> None:
    pdf.set_draw_color(100, 100, 100)
    pdf.line(15, pdf.get_y() + 1, 195, pdf.get_y() + 1)
    pdf.ln(4)


def make_prescription() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Dr. Arun Sharma, MBBS, MD (Internal Medicine)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "Reg. No: KA/45678/2015", ln=True)
    pdf.cell(0, 5, "City Medical Centre, 12 MG Road, Bengaluru - 560001", ln=True)
    pdf.cell(0, 5, "Ph: +91-80-41234567", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(100, 7, "Patient: Rajesh Kumar", border=0)
    pdf.cell(0, 7, "Date: 01-Nov-2024", ln=True)
    pdf.cell(0, 7, "Age: 39 years     Gender: Male", ln=True)
    pdf.cell(0, 7, "Chief Complaint: Fever since 3 days, body ache, headache", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Diagnosis: Viral Fever", ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Rx:", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "1. Tab Paracetamol 650mg  --  1-1-1  x 5 days", ln=True)
    pdf.cell(0, 7, "2. Tab Cetirizine 10mg    --  0-0-1  x 5 days", ln=True)
    pdf.cell(0, 7, "3. Tab Vitamin C 500mg    --  0-0-1  x 7 days", ln=True)
    pdf.cell(0, 7, "4. Syp. ORS (oral rehydration) -- as required", ln=True)
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(40, 7, "Investigations:")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "CBC, Dengue NS1 Antigen, Malaria Antigen", ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, "Advice: Rest, plenty of fluids, avoid cold foods.", ln=True)
    pdf.cell(0, 7, "Follow-up: After 5 days or earlier if condition worsens.", ln=True)
    pdf.ln(20)

    pdf.cell(130, 7, "")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Dr. Arun Sharma", ln=True)
    pdf.cell(130, 7, "")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Reg. No: KA/45678/2015", ln=True)
    pdf.cell(130, 6, "")
    pdf.cell(0, 6, "[Signature & Stamp]", ln=True)

    pdf.output(str(OUT / "prescription.pdf"))
    print("Created: prescription.pdf")


def make_hospital_bill() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "CITY MEDICAL CENTRE", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "12 MG Road, Bengaluru - 560001", ln=True, align="C")
    pdf.cell(0, 5, "GSTIN: 29ABCDE1234F1Z5   Ph: 080-41234567", ln=True, align="C")
    _divider(pdf)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "BILL / RECEIPT", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(100, 7, "Bill No: CMC/2024/08321")
    pdf.cell(0, 7, "Date: 01-Nov-2024", ln=True)
    _divider(pdf)

    pdf.cell(0, 7, "Patient Name:  Rajesh Kumar", ln=True)
    pdf.cell(0, 7, "Age / Gender:  39 / Male", ln=True)
    pdf.cell(0, 7, "Referring Doctor:  Dr. Arun Sharma", ln=True)
    _divider(pdf)

    # Table header
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(100, 8, "DESCRIPTION")
    pdf.cell(20, 8, "QTY", align="C")
    pdf.cell(30, 8, "RATE", align="R")
    pdf.cell(0, 8, "AMOUNT", align="R", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "", 11)
    rows = [
        ("Consultation Fee (OPD)", "1", "1,000.00", "1,000.00"),
        ("CBC (Complete Blood Count)", "1", "200.00", "200.00"),
        ("Dengue NS1 Antigen Test", "1", "300.00", "300.00"),
        ("Malaria Antigen Test", "1", "250.00", "250.00"),
    ]
    for desc, qty, rate, amt in rows:
        pdf.cell(100, 7, desc)
        pdf.cell(20, 7, qty, align="C")
        pdf.cell(30, 7, rate, align="R")
        pdf.cell(0, 7, amt, align="R", ln=True)

    _divider(pdf)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(150, 7, "Subtotal:")
    pdf.cell(0, 7, "1,750.00", align="R", ln=True)
    pdf.cell(150, 7, "GST (0% on medical services):")
    pdf.cell(0, 7, "0.00", align="R", ln=True)
    pdf.cell(150, 7, "Total Amount:")
    pdf.cell(0, 7, "1,750.00", align="R", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Payment Mode: Cash", ln=True)
    pdf.cell(0, 6, "Received by: Ramesh (Cashier)      [Cashier Stamp]", ln=True)

    pdf.output(str(OUT / "hospital_bill.pdf"))
    print("Created: hospital_bill.pdf")


def make_lab_report() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "PRECISION DIAGNOSTICS PVT LTD", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "NABL Accredited Lab  |  Lab ID: KA-NABL-1234", ln=True, align="C")
    pdf.cell(0, 5, "45 Jayanagar, Bengaluru  |  Ph: 080-27654321", ln=True, align="C")
    _divider(pdf)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(100, 7, "Patient: Rajesh Kumar")
    pdf.cell(0, 7, "Sample ID: PD-2024-18723", ln=True)
    pdf.cell(100, 7, "Age / Sex: 39 / Male")
    pdf.cell(0, 7, "Sample Date: 01-Nov-2024", ln=True)
    pdf.cell(100, 7, "Ref Doctor: Dr. Arun Sharma")
    pdf.cell(0, 7, "Report Date: 01-Nov-2024", ln=True)
    _divider(pdf)

    # Table header
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(70, 7, "TEST NAME")
    pdf.cell(30, 7, "RESULT", align="C")
    pdf.cell(20, 7, "UNIT", align="C")
    pdf.cell(0, 7, "NORMAL RANGE", align="C", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "COMPLETE BLOOD COUNT (CBC):", ln=True)
    pdf.set_font("Helvetica", "", 10)
    rows = [
        ("Hemoglobin", "13.2", "g/dL", "13.0 - 17.0"),
        ("WBC Count", "9,800", "/uL", "4,500 - 11,000"),
        ("Platelet Count", "1,85,000", "/uL", "1,50,000 - 4,50,000"),
        ("Neutrophils", "68", "%", "40 - 70"),
        ("Lymphocytes", "26", "%", "20 - 40"),
    ]
    for name, result, unit, ref in rows:
        pdf.cell(70, 6, f"  {name}")
        pdf.cell(30, 6, result, align="C")
        pdf.cell(20, 6, unit, align="C")
        pdf.cell(0, 6, ref, align="C", ln=True)

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "SEROLOGY:", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(70, 6, "  Dengue NS1 Antigen")
    pdf.cell(30, 6, "NEGATIVE", align="C")
    pdf.cell(20, 6, "--", align="C")
    pdf.cell(0, 6, "Negative", align="C", ln=True)
    pdf.cell(70, 6, "  Malaria Antigen (PF/PV)")
    pdf.cell(30, 6, "NEGATIVE", align="C")
    pdf.cell(20, 6, "--", align="C")
    pdf.cell(0, 6, "Negative", align="C", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, "Remarks: WBC count is towards upper normal limit. Clinical correlation advised.", ln=True)
    pdf.ln(10)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Dr. Meena Pillai, MD (Pathology)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Reg. No: KA/89012/2018    [Signature & Stamp]", ln=True)

    pdf.output(str(OUT / "lab_report.pdf"))
    print("Created: lab_report.pdf")


def make_pharmacy_bill() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "HEALTH FIRST PHARMACY", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, "Drug Lic. No: KA-BLR-DL-4521", ln=True, align="C")
    pdf.cell(0, 5, "22 Brigade Road, Bengaluru - 560025  |  Ph: 080-22334455", ln=True, align="C")
    _divider(pdf)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(100, 7, "Bill No: HFP-24-09821")
    pdf.cell(0, 7, "Date: 01-Nov-2024", ln=True)
    pdf.cell(100, 7, "Patient: Rajesh Kumar")
    pdf.cell(0, 7, "Dr: Dr. Arun Sharma", ln=True)
    _divider(pdf)

    # Table header
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(55, 7, "MEDICINE")
    pdf.cell(22, 7, "BATCH", align="C")
    pdf.cell(18, 7, "EXP", align="C")
    pdf.cell(15, 7, "QTY", align="C")
    pdf.cell(20, 7, "MRP", align="R")
    pdf.cell(0, 7, "AMT", align="R", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "", 10)
    rows = [
        ("Paracetamol 650mg", "A2341", "03/26", "15", "2.50", "37.50"),
        ("Cetirizine 10mg", "C7821", "11/25", "5", "3.00", "15.00"),
        ("Vitamin C 500mg", "B7821", "06/26", "10", "4.00", "40.00"),
        ("ORS Sachet (Electral)", "E1234", "08/26", "5", "12.00", "60.00"),
    ]
    for name, batch, exp, qty, mrp, amt in rows:
        pdf.cell(55, 6, name)
        pdf.cell(22, 6, batch, align="C")
        pdf.cell(18, 6, exp, align="C")
        pdf.cell(15, 6, qty, align="C")
        pdf.cell(20, 6, mrp, align="R")
        pdf.cell(0, 6, amt, align="R", ln=True)

    _divider(pdf)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(150, 7, "Subtotal:")
    pdf.cell(0, 7, "152.50", align="R", ln=True)
    pdf.cell(150, 7, "Discount (5%):")
    pdf.cell(0, 7, "-7.63", align="R", ln=True)
    pdf.cell(150, 7, "Net Amount:")
    pdf.cell(0, 7, "144.87", align="R", ln=True)
    _divider(pdf)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Pharmacist: R. Sharma      [Pharmacist Stamp]", ln=True)

    pdf.output(str(OUT / "pharmacy_bill.pdf"))
    print("Created: pharmacy_bill.pdf")


if __name__ == "__main__":
    make_prescription()
    make_hospital_bill()
    make_lab_report()
    make_pharmacy_bill()
    print(f"\nAll sample documents saved to: {OUT}")
