from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether, PageBreak,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Technical Design Document.pdf"
INK = colors.HexColor("#1B2430")
MUTED = colors.HexColor("#596678")
GREEN = colors.HexColor("#227522")
NAVY = colors.HexColor("#172033")
PALE = colors.HexColor("#F1F4F7")
BORDER = colors.HexColor("#D7DDE5")


class TddDoc(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(filename, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm, topMargin=17*mm, bottomMargin=17*mm, title="FleetPOD Technical Design Document", author="FleetPOD take-home project")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(self.leftMargin, 10*mm, "FleetPOD  |  Technical Design Document")
        canvas.drawRightString(A4[0] - self.rightMargin, 10*mm, f"Page {doc.page}")
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(.5)
        canvas.line(self.leftMargin, 13*mm, A4[0] - self.rightMargin, 13*mm)
        canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TddTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=colors.black, alignment=TA_LEFT, spaceAfter=3*mm))
styles.add(ParagraphStyle(name="TddSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=11, leading=14, textColor=MUTED, spaceAfter=3*mm))
styles.add(ParagraphStyle(name="TddUrl", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=12, textColor=INK, spaceAfter=5*mm))
styles.add(ParagraphStyle(name="TddH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.black, spaceBefore=4*mm, spaceAfter=2*mm, keepWithNext=True))
styles.add(ParagraphStyle(name="TddH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.black, spaceBefore=2*mm, spaceAfter=1.5*mm, keepWithNext=True))
styles.add(ParagraphStyle(name="TddBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12.4, textColor=INK, spaceAfter=2.2*mm))
styles.add(ParagraphStyle(name="TddSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.7, leading=10.2, textColor=INK, spaceAfter=0))
styles.add(ParagraphStyle(name="TddCellHeader", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9.4, textColor=colors.white, spaceAfter=0))
styles.add(ParagraphStyle(name="TddBullet", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.7, leading=12, textColor=INK, leftIndent=11, firstLineIndent=-7, bulletIndent=0, spaceAfter=1.2*mm))


def P(text, style="TddBody"):
    return Paragraph(text, styles[style])


def bullet(text):
    return Paragraph(f"- &nbsp; {text}", styles["TddBullet"])


def make_table(headers, rows, widths):
    data = [[P(text, "TddCellHeader") for text in headers]]
    data.extend([[P(str(value), "TddSmall") for value in row] for row in rows])
    tbl = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [PALE, colors.white]),
        ("GRID", (0,0), (-1,-1), .45, BORDER),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return tbl


story = [
    P("FleetPOD Technical Design Document", "TddTitle"),
    P("Proof of delivery capture, verification, and billing", "TddSubtitle"),
    P("GitHub URL: https://github.com/chaitanya-maddala-236/fleetpod-pod-billing  |  Live app: https://fleetpod.onrender.com", "TddUrl"),
    P("FleetPOD moves proof of delivery closer to the delivery gate so billing can begin sooner. This build covers the core route from driver photo capture through an AI check and human exception handling to a Tally-ready export. The photo remains the source of truth, and a billing executive controls corrections and invoice marking."),
    P("1  Product scope and user experience", "TddH1"),
    P("The interface follows the brief's minimal OLED direction: a true-black canvas, quiet charcoal surfaces, clear gray body text, and distinct green, blue, gold, and purple cues. Drivers see their trips and one large capture action. Billing staff see missing proof, uncertain readings, and verified trips in separate focused views. The layout adapts to mobile widths, and the driver capture screen includes Hindi and Marathi spoken instructions."),
    make_table(["Role", "Main actions", "Access boundary"], [
        ["Driver", "Select demo trip, photograph or choose a POD, retry a requested photo, queue capture offline.", "Can upload photos and view demo trip details; cannot verify or invoice."],
        ["Billing executive", "Correct extracted fields, verify or request a retake, export CSV, mark invoices, view dashboard.", "Can review and bill trips; every decision is logged."],
        ["Client viewer", "Open a tokenized, read-only trip link and view its POD image.", "Can view one trip only; no edit or list access."],
    ], [31*mm, 82*mm, 63*mm]),
    P("Core flows", "TddH2"),
]
for text in [
    "Driver selects a trip, takes a photo, and the browser stamps capture time and optional GPS coordinates. The image is resized and JPEG-compressed below 300 KB.",
    "If the network is unavailable, the photo and metadata are stored in IndexedDB and sent when the connection returns. The UI shows the queued count.",
    "The vision check reads the LR number, consignee stamp, quantity, shortage or damage remarks, delivery date, and signature. Missing credentials or a model error sends the POD to human review.",
    "A clean high-confidence match becomes verified. Shortage or damage, low confidence, missing fields, and mismatches require human review or a retake. Retakes are capped at two.",
    "A billing executive corrects fields against the original image, then verifies the POD. Verified trips enter the billing queue; staff export a CSV with a POD image link and mark invoices manually.",
]:
    story.append(bullet(text))

story += [
    P("2  Architecture and data model", "TddH1"),
    make_table(["Layer", "Implementation", "Reason"], [
        ["Frontend", "Responsive HTML, CSS, and JavaScript served by FastAPI; PWA shell and IndexedDB queue.", "A small dependency-free interface loads on basic mobile devices and keeps capture usable during network drops."],
        ["Backend", "FastAPI JSON routes with signed session cookies and role checks.", "Separates driver upload from billing review and keeps validation and decision rules server-side."],
        ["Storage", "SQLite locally; Neon PostgreSQL through DATABASE_URL when hosted. Compressed POD bytes are stored in BYTEA.", "Trip data and images survive free Render restarts without a persistent host disk. Move binary images to object storage for production."],
        ["Vision AI", "Optional OpenAI Responses API call with the compressed photo and a structured field schema.", "Produces machine-readable extraction while keeping verification and exception decisions explicit."],
    ], [27*mm, 77*mm, 72*mm]),
    Spacer(1, 2*mm),
    P("Request path: Driver PWA -> FastAPI session and role check -> image validation and compression -> optional vision check -> trip status and audit row -> review queue or billing queue. The offline queue stores pending photo data in the browser and retries after reconnection. Client links use a random per-trip token and return a read-only view."),
    make_table(["Entity", "Important fields", "Relationship / purpose"], [
        ["User", "email, display name, role, PBKDF2 salt and digest", "Authenticates driver and billing roles."],
        ["Trip", "client, vehicle, destination, branch, freight, LR, e-way bill, expected quantity, status, timestamps, retake count, image metadata and bytes, AI fields, share token", "One trip is the unit of POD capture, review, billing, and client sharing."],
        ["Audit log", "actor, action, trip ID, detail, UTC timestamp", "Records upload, AI result, human decision, CSV export, and invoice marking."],
        ["Upload link", "random token, trip ID, expiry, used timestamp", "Mocks a one-time hired-driver SMS upload link; expires after 24 hours."],
    ], [27*mm, 78*mm, 71*mm]),
    P("3  POD vision check and exception handling", "TddH1"),
    P("The server sends an uploaded JPEG as a base64 data URL to a vision-capable Responses API model when OPENAI_API_KEY is configured. The request asks for the LR number, stamp visibility, quantity, shortage or damage remarks, delivery date, signature visibility, confidence, and short issues. A JSON schema constrains the response. The request sets store=false."),
    make_table(["Condition", "System result", "Next step"], [
        ["Strong confidence, matching LR and quantity, stamp and signature present, no shortage or damage", "Verified", "Available for billing export."],
        ["Any shortage or damage remark, or a quantity difference", "Needs review", "Billing executive compares the extracted fields and image."],
        ["Low confidence, unreadable or missing required fields, or LR mismatch", "Retake requested", "Driver takes a clearer photo. After two retakes the case goes to human review."],
        ["No API key, API error, invalid model output, or no network", "Needs review", "No automatic verification; billing executive uses the image as evidence."],
    ], [69*mm, 34*mm, 73*mm]),
    Spacer(1, 2*mm),
    P("The API response never directly approves an invoice. The backend checks the extracted LR and quantity against the trip, applies confidence and exception rules, and stores the original photo. Internal image access requires a signed-in role; a client can retrieve one image through its unguessable read-only trip token. Billing users can edit extracted values and add an audit note."),
    P("4  Interface, accessibility, and security", "TddH1"),
    make_table(["Screen", "Design decision"], [
        ["Driver capture", "A trip card and a large camera action; optional Hindi or Marathi speech; capture time and GPS shown after selection; no driver text form."],
        ["Review queue", "Exception reason, original photo, editable fields, confidence, and clear verify or retake actions in one view."],
        ["Billing queue", "Verified trips only, with LR and e-way bill, freight, POD image, client link, export, and manual invoice marking."],
        ["Missing-POD dashboard", "Four key metrics, follow-up table, and branch-level outstanding counts; tables scroll horizontally on small phones."],
    ], [37*mm, 139*mm]),
    Spacer(1, 1.5*mm),
    bullet("Body copy uses light gray on black or charcoal. Accent colors are reserved for status and action cues; focus outlines remain white and visible."),
    bullet("Reduced-motion preferences disable nonessential animation. Icon-only controls have accessible names. Input validation is performed in the browser and server."),
    bullet("Passwords use PBKDF2-HMAC-SHA256 with unique random salts. Sessions use signed, same-site cookies. Role-protected routes gate review, export, and invoice actions. The API key comes from the environment, `.env` is ignored by Git, and demo data is synthetic."),
    bullet("Uploads accept supported image types, are decoded and re-encoded server-side, and are capped at 300 KB. Security headers limit framing, MIME sniffing, and content sources."),
    P("5  Tests and operational limits", "TddH1"),
    P("The test suite covers authentication, role boundaries, the offline app shell, no-key fallback, exception classification, the two-retake limit, human review to billing export, one-time upload links, and invoice timing. The latest run completed with 8 passing tests. The public free demo has no paid vision API credential configured, so POD uploads go to manual review; a private OPENAI_API_KEY enables live vision extraction."),
    P("Assumptions", "TddH2"),
    bullet("OpenAI was selected as the vision provider because the brief does not name a provider."),
    bullet("Additional LR and e-way bill values, branch assignments, trip dates, quantities, demo account names, and POD images are synthetic values created for this prototype."),
    bullet("A verified POD may enter the billing queue only after a clean machine check or a billing executive's explicit verification."),
    bullet("The client share link is a single-trip read-only token link. API failure or missing credentials must prefer review over automatic approval."),
    bullet("The public reviewer accounts and trips are synthetic. Render Free may sleep after inactivity; its filesystem is temporary, while Neon is the persistence layer."),
    P("Cut for this build", "TddH2"),
    P("Live SMS and Tally integrations, daily trip CSV import, real client contact details, production hosting, live GPS tracking, trip planning, and fuel or driver-expense accounting are out of this build. SMS is represented by a single-use upload link; Tally is represented by a downloadable CSV."),
    P("Next steps", "TddH2"),
    P("Add daily trip CSV import, move production POD binaries to object storage, agree retention and deletion rules, validate branch access and audit retention, and test vision rules against privacy-cleared documents. The free deployment is a reviewer demo, not a production service."),
    P("References", "TddH2"),
    P("OpenAI Images and Vision: https://developers.openai.com/api/docs/guides/images-vision  |  Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs", "TddSmall"),
]

doc = TddDoc(str(OUTPUT))
doc.build(story)
print(OUTPUT)
