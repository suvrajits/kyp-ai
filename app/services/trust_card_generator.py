# app/services/trust_card_generator.py

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import io
from datetime import datetime


def generate_trust_card_pdf(structured, matched, confidence, status) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Colors
    blue = HexColor("#0077cc")
    gray = HexColor("#666")
    green = HexColor("#28a745")
    orange = HexColor("#ffc107")

    # Header
    c.setFillColor(blue)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height - 70, "🪪 Provider Trust Verification")

    c.setStrokeColor(blue)
    c.line(50, height - 80, width - 50, height - 80)

    y = height - 120
    c.setFillColor(gray)
    c.setFont("Helvetica", 12)

    def draw_label_value(label, value):
        nonlocal y
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(gray)
        c.drawString(60, y, f"{label}:")
        c.setFont("Helvetica", 11)
        c.setFillColor("#000000")
        c.drawString(180, y, value)
        y -= 24

    # Structured Fields
    draw_label_value("Provider Name", structured.get("provider_name", ""))
    draw_label_value("License Number", structured.get("license_number", ""))
    draw_label_value("Specialty", structured.get("specialty", ""))
    draw_label_value("Issuing Authority", structured.get("issuing_authority", ""))
    draw_label_value("Validity", f"{structured.get('issue_date')} to {structured.get('expiry_date')}")

    # Match Confidence
    y -= 10
    draw_label_value("Confidence Score", f"{round(confidence * 100, 2)}%")
    draw_label_value("Match Status", status)

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(gray)
    c.drawCentredString(width / 2, 60, "This Trust Card is auto-generated for verification purposes only.")
    c.drawCentredString(width / 2, 45, f"Issued on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()
