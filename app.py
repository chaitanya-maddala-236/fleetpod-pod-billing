from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from PIL import Image, ImageDraw, ImageFont
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import psycopg


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def configured_path(variable: str, default: Path) -> Path:
    value = Path(os.getenv(variable, str(default))).expanduser()
    return value if value.is_absolute() else ROOT / value


DATA_DIR = configured_path("DATA_DIR", ROOT / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = ROOT / "static"
DATABASE_PATH = configured_path("DATABASE_PATH", DATA_DIR / "fleetpod.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_POD_BYTES = 300_000
logger = logging.getLogger("fleetpod")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    columns = [column.name for column in cursor.description]
    return lambda values: HybridRow(zip(columns, values))


class PostgresConnection:
    def __init__(self, database_url: str):
        self.connection = psycopg.connect(database_url, row_factory=hybrid_row)

    def execute(self, query: str, parameters=()):
        return self.connection.execute(query.replace("?", "%s"), parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
        return False


def connect() -> sqlite3.Connection | PostgresConnection:
    if DATABASE_URL:
        return PostgresConnection(DATABASE_URL)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def password_digest(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    _, candidate = password_digest(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, digest_hex)


def _make_demo_pod(filename: str, lr: str, consignee: str, issue: str | None = None) -> str:
    path = UPLOAD_DIR / filename
    if path.exists():
        return filename
    image = Image.new("RGB", (1100, 780), "#f5f4ef")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=27)
    small = ImageFont.load_default(size=21)
    draw.rounded_rectangle((36, 36, 1064, 744), radius=14, fill="#fffefa", outline="#d1d5db", width=3)
    draw.text((78, 78), "DEMO PROOF OF DELIVERY", fill="#172033", font=font)
    draw.text((78, 125), f"Lorry Receipt: {lr}", fill="#303b4d", font=small)
    draw.text((78, 170), f"Consignee: {consignee}", fill="#303b4d", font=small)
    draw.line((78, 224, 1020, 224), fill="#cbd5e1", width=2)
    draw.text((78, 270), "Delivery quantity: 24 cartons", fill="#303b4d", font=small)
    draw.text((78, 318), "Received at destination gate", fill="#303b4d", font=small)
    draw.text((78, 368), f"Remarks: {issue or 'Nil'}", fill="#303b4d", font=small)
    draw.text((78, 430), "Date: 02 Nov 2026", fill="#303b4d", font=small)
    draw.line((78, 570, 480, 570), fill="#6b7280", width=2)
    draw.text((78, 586), "Consignee signature", fill="#6b7280", font=small)
    if issue == "Stamp not visible":
        draw.ellipse((735, 420, 930, 615), outline="#d1d5db", width=4)
        draw.text((754, 500), "STAMP", fill="#d1d5db", font=small)
    else:
        draw.ellipse((735, 420, 930, 615), outline="#cc453d", width=6)
        draw.text((765, 495), "RECEIVED", fill="#cc453d", font=small)
        draw.text((783, 530), "GATE SEAL", fill="#cc453d", font=small)
    if issue:
        draw.line((80, 520, 420, 466), fill="#172033", width=4)
        draw.line((90, 475, 360, 530), fill="#172033", width=3)
    image.save(path, "JPEG", quality=76, optimize=True)
    return filename


def initialize_database() -> None:
    with connect() as db:
        if DATABASE_URL:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('driver', 'billing')),
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    client TEXT NOT NULL,
                    vehicle TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    freight INTEGER NOT NULL CHECK (freight >= 0),
                    lr_number TEXT NOT NULL,
                    eway_bill TEXT NOT NULL,
                    expected_qty TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (status IN ('missing', 'uploaded', 'verified', 'retake_requested', 'needs_review')),
                    remarks TEXT NOT NULL DEFAULT '',
                    delivered_at TEXT,
                    pod_at TEXT,
                    invoice_at TEXT,
                    retake_count INTEGER NOT NULL DEFAULT 0,
                    pod_image TEXT,
                    pod_image_data BYTEA,
                    ai_result TEXT,
                    share_token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    actor_email TEXT NOT NULL,
                    action TEXT NOT NULL,
                    trip_id TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trip_id) REFERENCES trips(id)
                );
                CREATE TABLE IF NOT EXISTS upload_links (
                    token TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    FOREIGN KEY(trip_id) REFERENCES trips(id)
                );
                CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status);
                CREATE INDEX IF NOT EXISTS idx_trips_delivered ON trips(delivered_at);
                ALTER TABLE trips ADD COLUMN IF NOT EXISTS pod_image_data BYTEA;
                """
            )
        else:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('driver', 'billing')),
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    client TEXT NOT NULL,
                    vehicle TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    freight INTEGER NOT NULL CHECK (freight >= 0),
                    lr_number TEXT NOT NULL,
                    eway_bill TEXT NOT NULL,
                    expected_qty TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (status IN ('missing', 'uploaded', 'verified', 'retake_requested', 'needs_review')),
                    remarks TEXT NOT NULL DEFAULT '',
                    delivered_at TEXT,
                    pod_at TEXT,
                    invoice_at TEXT,
                    retake_count INTEGER NOT NULL DEFAULT 0,
                    pod_image TEXT,
                    pod_image_data BLOB,
                    ai_result TEXT,
                    share_token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_email TEXT NOT NULL,
                    action TEXT NOT NULL,
                    trip_id TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trip_id) REFERENCES trips(id)
                );
                CREATE TABLE IF NOT EXISTS upload_links (
                    token TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    FOREIGN KEY(trip_id) REFERENCES trips(id)
                );
                CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status);
                CREATE INDEX IF NOT EXISTS idx_trips_delivered ON trips(delivered_at);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(trips)").fetchall()}
            if "pod_image_data" not in columns:
                db.execute("ALTER TABLE trips ADD COLUMN pod_image_data BLOB")

        legacy_images = db.execute("SELECT id,pod_image FROM trips WHERE pod_image IS NOT NULL AND pod_image_data IS NULL").fetchall()
        for row in legacy_images:
            legacy_path = UPLOAD_DIR / row["pod_image"]
            if legacy_path.is_file():
                db.execute("UPDATE trips SET pod_image_data=? WHERE id=?", (legacy_path.read_bytes(), row["id"]))

        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = [
                ("driver@fleetpod.demo", "Demo Driver", "driver", "DriverDemo26!"),
                ("billing@fleetpod.demo", "Asha Kulkarni", "billing", "BillingDemo26!"),
            ]
            for email, name, role, password in users:
                salt, digest = password_digest(password)
                db.execute(
                    "INSERT INTO users(email,name,role,password_salt,password_hash) VALUES(?,?,?,?,?)",
                    (email, name, role, salt, digest),
                )
        if db.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0:
            now = utc_now()
            seed_trips = [
                ("TRP-66120", "Company B (cement)", "MH20 EL 4521", "Nagpur", "Chhatrapati Sambhajinagar", 38500, "LR-66120", "EWB-2710-66120", "24 cartons", "verified", "None", 3, 2, 0),
                ("TRP-66134", "Company C (steel)", "MH20 GT 7718", "Pune", "Pune", 26000, "LR-66134", "EWB-2710-66134", "18 bundles", "retake_requested", "Stamp not visible", 1, 0, 0),
                ("TRP-66141", "Company D (packaged foods)", "MH17 BY 3092 (hired)", "Indore", "Chhatrapati Sambhajinagar", 41200, "LR-66141", "EWB-2710-66141", "120 cartons", "needs_review", "Short by 6 cartons", 2, 1, 0),
                ("TRP-66152", "Company B (cement)", "MH20 JK 1184", "Aurangabad", "Chhatrapati Sambhajinagar", 33100, "LR-66152", "EWB-2710-66152", "40 bags", "missing", "Awaiting POD", 0, 0, 0),
                ("TRP-66167", "Company C (steel)", "MH14 LM 9090", "Nashik", "Pune", 29500, "LR-66167", "EWB-2710-66167", "12 coils", "missing", "Awaiting POD", 1, 0, 0),
                ("TRP-66173", "Company D (packaged foods)", "MH20 NP 6342", "Bhopal", "Chhatrapati Sambhajinagar", 39800, "LR-66173", "EWB-2710-66173", "80 cartons", "missing", "Awaiting POD", 4, 0, 0),
                ("TRP-66188", "Company B (cement)", "MH20 QR 4511", "Amravati", "Chhatrapati Sambhajinagar", 28700, "LR-66188", "EWB-2710-66188", "32 bags", "verified", "None", 5, 3, 1),
                ("TRP-66204", "Company C (steel)", "MH12 ST 2235 (hired)", "Kolhapur", "Pune", 35400, "LR-66204", "EWB-2710-66204", "20 sheets", "missing", "Awaiting POD", 0, 0, 0),
            ]
            for row in seed_trips:
                trip_id, client, vehicle, destination, branch, freight, lr, eway, qty, status, remarks, delivered_days, pod_days, invoiced_days = row
                pod_filename = None
                ai_result = None
                if status == "verified":
                    pod_filename = _make_demo_pod(f"{trip_id.lower()}-demo.jpg", lr, client)
                    ai_result = json.dumps({"lr_number": lr, "consignee_stamp_visible": True, "quantity_received": qty, "shortage_or_damage_remarks": "", "delivery_date": (now - timedelta(days=delivered_days)).date().isoformat(), "signature_visible": True, "confidence": 0.96, "issues": []})
                elif status == "retake_requested":
                    pod_filename = _make_demo_pod(f"{trip_id.lower()}-demo.jpg", lr, client, "Stamp not visible")
                    ai_result = json.dumps({"lr_number": lr, "consignee_stamp_visible": False, "quantity_received": qty, "shortage_or_damage_remarks": "", "delivery_date": (now - timedelta(days=delivered_days)).date().isoformat(), "signature_visible": True, "confidence": 0.73, "issues": ["Consignee stamp is not clearly visible"]})
                elif status == "needs_review":
                    pod_filename = _make_demo_pod(f"{trip_id.lower()}-demo.jpg", lr, client, remarks)
                    ai_result = json.dumps({"lr_number": lr, "consignee_stamp_visible": True, "quantity_received": "114 cartons", "shortage_or_damage_remarks": remarks, "delivery_date": (now - timedelta(days=delivered_days)).date().isoformat(), "signature_visible": True, "confidence": 0.92, "issues": [remarks]})
                delivered_at = now - timedelta(days=delivered_days)
                pod_at = now - timedelta(days=pod_days) if pod_days else None
                invoice_at = now - timedelta(days=invoiced_days) if invoiced_days else None
                pod_image_data = (UPLOAD_DIR / pod_filename).read_bytes() if pod_filename else None
                db.execute(
                    """INSERT INTO trips(id,client,vehicle,destination,branch,freight,lr_number,eway_bill,expected_qty,status,remarks,delivered_at,pod_at,invoice_at,retake_count,pod_image,pod_image_data,ai_result,share_token,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (trip_id, client, vehicle, destination, branch, freight, lr, eway, qty, status, remarks,
                     iso(delivered_at), iso(pod_at), iso(invoice_at), 1 if status == "retake_requested" else 0,
                     pod_filename, pod_image_data, ai_result, secrets.token_urlsafe(24), iso(now)),
                )


try:
    initialize_database()
except Exception as exc:
    # Do not log DATABASE_URL or exception text, which can contain connection details.
    logger.exception(
        "FleetPOD database initialization failed (%s); DATABASE_URL configured=%s",
        type(exc).__name__,
        bool(DATABASE_URL),
    )
    raise

app = FastAPI(title="FleetPOD", version="1.0.0")
session_secret = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    same_site="lax",
    https_only=os.getenv("ENVIRONMENT", "development").lower() == "production",
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


class LoginInput(BaseModel):
    email: str = Field(min_length=6, max_length=120)
    password: str = Field(min_length=8, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("Enter a valid email address")
        return value


class PodInput(BaseModel):
    image_data: str = Field(min_length=40, max_length=450_000)
    captured_at: str = Field(min_length=10, max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ReviewInput(BaseModel):
    action: Literal["verify", "retake"]
    lr_number: str = Field(default="", max_length=50)
    consignee_stamp_visible: bool = False
    quantity_received: str = Field(default="", max_length=100)
    shortage_or_damage_remarks: str = Field(default="", max_length=300)
    delivery_date: str = Field(default="", max_length=30)
    signature_visible: bool = False
    correction_note: str = Field(default="", max_length=300)


def current_user(request: Request) -> dict[str, Any]:
    email = request.session.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    with connect() as db:
        row = db.execute("SELECT id,email,name,role FROM users WHERE email=?", (email,)).fetchone()
    if not row:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return dict(row)


def require_role(*roles: str):
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="This action is not available for your role")
        return user
    return dependency


def log_action(db: sqlite3.Connection, user: dict[str, Any], action: str, trip_id: str | None, detail: str = "") -> None:
    db.execute(
        "INSERT INTO audit_log(actor_email,action,trip_id,detail,created_at) VALUES(?,?,?,?,?)",
        (user["email"], action, trip_id, detail[:300], iso(utc_now())),
    )


def trip_json(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result.pop("pod_image_data", None)
    result["pod_url"] = f"/api/pods/{row['id']}/image" if row["pod_image"] else None
    result["ai_result"] = json.loads(row["ai_result"]) if row["ai_result"] else None
    result["share_url"] = f"/share/{row['share_token']}"
    return result


def get_trip(db: sqlite3.Connection, trip_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")
    return row


def normalize_ai_result(raw: dict[str, Any], trip: sqlite3.Row) -> dict[str, Any]:
    confidence = raw.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    lr_number = str(raw.get("lr_number") or "").strip()
    remarks = str(raw.get("shortage_or_damage_remarks") or "").strip()
    issues = [str(item)[:150] for item in raw.get("issues", [])[:8] if item]
    if lr_number and lr_number.upper().replace(" ", "") != trip["lr_number"].upper().replace(" ", ""):
        issues.append("LR number does not match this trip")
    if not raw.get("consignee_stamp_visible"):
        issues.append("Consignee stamp is missing or unclear")
    if not raw.get("signature_visible"):
        issues.append("Consignee signature is missing or unclear")
    if not raw.get("delivery_date"):
        issues.append("Delivery date could not be read")
    if not raw.get("quantity_received"):
        issues.append("Delivered quantity could not be read")
    expected_match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(trip["expected_qty"]))
    received_match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(raw.get("quantity_received") or ""))
    quantity_mismatch = bool(expected_match and received_match and float(expected_match.group().replace(",", "")) != float(received_match.group().replace(",", "")))
    if quantity_mismatch:
        issues.append("Delivered quantity differs from the trip quantity")
    return {
        "lr_number": lr_number,
        "consignee_stamp_visible": bool(raw.get("consignee_stamp_visible")),
        "quantity_received": str(raw.get("quantity_received") or "").strip(),
        "shortage_or_damage_remarks": remarks,
        "delivery_date": str(raw.get("delivery_date") or "").strip(),
        "signature_visible": bool(raw.get("signature_visible")),
        "confidence": confidence,
        "issues": list(dict.fromkeys(issues)),
        "quantity_mismatch": quantity_mismatch,
    }


def decide_pod_status(result: dict[str, Any], trip: sqlite3.Row) -> tuple[str, str]:
    if result["shortage_or_damage_remarks"] or result.get("quantity_mismatch"):
        return "needs_review", "Shortage, damage, or quantity difference needs a billing executive"
    if result["confidence"] < 0.82:
        return "retake_requested", "Image confidence is low; take a clearer photo"
    if result["issues"]:
        return "retake_requested", result["issues"][0]
    if not result["consignee_stamp_visible"] or not result["signature_visible"]:
        return "retake_requested", "Stamp or signature is not clear; retake the photo"
    return "verified", "POD verified"


async def vision_check(image_bytes: bytes, mime_type: str, trip: sqlite3.Row) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    schema = {
        "type": "object",
        "properties": {
            "lr_number": {"type": "string"},
            "consignee_stamp_visible": {"type": "boolean"},
            "quantity_received": {"type": "string"},
            "shortage_or_damage_remarks": {"type": "string"},
            "delivery_date": {"type": "string"},
            "signature_visible": {"type": "boolean"},
            "confidence": {"type": "number"},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["lr_number", "consignee_stamp_visible", "quantity_received", "shortage_or_damage_remarks", "delivery_date", "signature_visible", "confidence", "issues"],
        "additionalProperties": False,
    }
    image_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    prompt = (
        "Inspect this proof-of-delivery image. Do not infer unreadable values. Extract the LR number, whether a consignee stamp is visible, delivered quantity, any shortage or damage remarks, date, signature visibility, a confidence score from 0 to 1, and short issues. "
        f"Expected LR number: {trip['lr_number']}. Expected consignee/client: {trip['client']}. Expected shipment quantity: {trip['expected_qty']}. "
        "Treat any shortage or damage text as a human-review case. Return an empty string for fields you cannot read. Output only the required structured fields."
    )
    payload = {
        "model": model,
        "store": False,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_url, "detail": "high"},
        ]}],
        "text": {"format": {"type": "json_schema", "name": "pod_check", "strict": True, "schema": schema}},
    }
    async with httpx.AsyncClient(timeout=50) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    response.raise_for_status()
    body = response.json()
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return json.loads(content["text"])
    raise ValueError("Vision model returned no structured output")


async def evaluate_pod(image_bytes: bytes, mime_type: str, trip: dict[str, Any], retake_count: int) -> tuple[str, str, dict[str, Any] | None]:
    try:
        raw = await vision_check(image_bytes, mime_type, trip)
        if raw is None:
            result = None
            status, reason = "needs_review", "Vision AI is not configured; image sent to billing review"
        else:
            result = normalize_ai_result(raw, trip)
            status, reason = decide_pod_status(result, trip)
    except Exception:
        result = None
        status, reason = "needs_review", "Vision AI could not read this image; billing review is required"
    if status == "retake_requested" and retake_count >= 2:
        status, reason = "needs_review", "Two retakes have been used; billing review is required"
    return status, reason, result


def validate_data_image(data_url: str) -> tuple[bytes, str]:
    if "," not in data_url:
        raise HTTPException(status_code=422, detail="Photo data is invalid")
    header, encoded = data_url.split(",", 1)
    mime_type = header.removeprefix("data:").split(";", 1)[0].lower()
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Use a JPG, PNG, or WebP photo")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_POD_BYTES:
            raise HTTPException(status_code=413, detail="Compress the photo to 300 KB or less")
        image = Image.open(io.BytesIO(raw))
        image.verify()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Photo could not be read") from exc
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((2400, 2400))
    buffer = io.BytesIO()
    quality = 88
    while quality >= 42:
        buffer.seek(0)
        buffer.truncate(0)
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        if buffer.tell() <= MAX_POD_BYTES:
            break
        quality -= 8
        if quality == 56:
            image.thumbnail((1600, 1600))
    if buffer.tell() > MAX_POD_BYTES:
        raise HTTPException(status_code=413, detail="Photo is too large after compression")
    return buffer.getvalue(), "image/jpeg"


@app.get("/", response_class=HTMLResponse)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", headers={"Service-Worker-Allowed": "/"})


@app.get("/share/{token}", response_class=HTMLResponse)
def share_page(token: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/upload/{token}", response_class=HTMLResponse)
def upload_page(token: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/pods/{trip_id}/image")
def private_pod_image(trip_id: str, user: dict[str, Any] = Depends(current_user)) -> Response:
    with connect() as db:
        trip = db.execute("SELECT pod_image,pod_image_data FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not trip or not trip["pod_image"]:
        raise HTTPException(status_code=404, detail="POD image is not available")
    image_data = trip["pod_image_data"]
    if image_data:
        return Response(content=image_data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    legacy_path = UPLOAD_DIR / trip["pod_image"]
    if legacy_path.is_file():
        return FileResponse(legacy_path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    raise HTTPException(status_code=404, detail="POD image is not available")


@app.get("/api/share/{token}/image")
def shared_pod_image(token: str) -> Response:
    with connect() as db:
        row = db.execute("SELECT pod_image,pod_image_data FROM trips WHERE share_token=?", (token,)).fetchone()
    if not row or not row["pod_image"]:
        raise HTTPException(status_code=404, detail="POD image is not available")
    if row["pod_image_data"]:
        return Response(content=row["pod_image_data"], media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    legacy_path = UPLOAD_DIR / row["pod_image"]
    if legacy_path.is_file():
        return FileResponse(legacy_path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    raise HTTPException(status_code=404, detail="POD image is not available")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "FleetPOD"}


@app.post("/api/login")
def login(payload: LoginInput, request: Request, response: Response) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (payload.email,)).fetchone()
    if not row or not verify_password(payload.password, row["password_salt"], row["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    request.session.clear()
    request.session["email"] = row["email"]
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


@app.post("/api/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.get("/api/trips")
def trips(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM trips ORDER BY delivered_at DESC, id").fetchall()
    if user["role"] == "driver":
        # The demo driver sees the sample trips assigned to their route.
        rows = [row for row in rows if row["status"] != "verified" or row["id"] == "TRP-66120"]
    return [trip_json(row) for row in rows]


@app.post("/api/trips/{trip_id}/pod")
async def upload_pod(
    trip_id: str,
    payload: PodInput,
    user: dict[str, Any] = Depends(require_role("driver")),
) -> dict[str, Any]:
    image_bytes, mime_type = validate_data_image(payload.image_data)
    try:
        captured_at = datetime.fromisoformat(payload.captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Capture time is invalid") from exc
    if captured_at > utc_now() + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Capture time cannot be in the future")
    with connect() as db:
        trip = get_trip(db, trip_id)
        if trip["status"] == "verified":
            raise HTTPException(status_code=409, detail="This trip already has a verified POD")
        if trip["status"] == "retake_requested" and trip["retake_count"] >= 2:
            raise HTTPException(status_code=409, detail="Two retakes have been used; ask billing to review the POD")
        retake_count = trip["retake_count"] + (1 if trip["status"] == "retake_requested" else 0)
        trip_context = dict(trip)
        filename = f"{trip_id.lower()}-{secrets.token_hex(8)}.jpg"
        db.execute("UPDATE trips SET status='uploaded',pod_image=?,pod_image_data=?,pod_at=?,remarks=?,ai_result=NULL WHERE id=?", (filename, image_bytes, iso(captured_at), "AI check in progress", trip_id))
        log_action(db, user, "pod_uploaded", trip_id, f"Captured {payload.captured_at}; GPS {payload.latitude},{payload.longitude}")
    status, reason, result = await evaluate_pod(image_bytes, mime_type, trip_context, retake_count)
    with connect() as db:
        db.execute("UPDATE trips SET status=?,remarks=?,ai_result=?,retake_count=? WHERE id=? AND pod_image=?", (status, reason, json.dumps(result) if result else None, retake_count, trip_id, filename))
        log_action(db, user, "ai_checked" if result else "ai_unavailable", trip_id, reason)
        updated = get_trip(db, trip_id)
    return {"trip": trip_json(updated), "retake_limit": 2, "retakes_used": updated["retake_count"]}


@app.post("/api/trips/{trip_id}/review")
def review_pod(
    trip_id: str,
    payload: ReviewInput,
    user: dict[str, Any] = Depends(require_role("billing")),
) -> dict[str, Any]:
    with connect() as db:
        trip = get_trip(db, trip_id)
        if trip["status"] not in {"needs_review", "retake_requested"}:
            raise HTTPException(status_code=409, detail="This trip is not waiting for billing review")
        result = json.loads(trip["ai_result"]) if trip["ai_result"] else {}
        result.update({
            "lr_number": payload.lr_number.strip(),
            "consignee_stamp_visible": payload.consignee_stamp_visible,
            "quantity_received": payload.quantity_received.strip(),
            "shortage_or_damage_remarks": payload.shortage_or_damage_remarks.strip(),
            "delivery_date": payload.delivery_date.strip(),
            "signature_visible": payload.signature_visible,
        })
        if payload.action == "retake":
            if trip["retake_count"] >= 2:
                raise HTTPException(status_code=409, detail="The two retakes have already been used")
            db.execute("UPDATE trips SET status='retake_requested',remarks='Billing executive requested a clearer POD',ai_result=? WHERE id=?", (json.dumps(result), trip_id))
            log_action(db, user, "retake_requested", trip_id, payload.correction_note or "")
        else:
            if not payload.lr_number.strip() or not payload.quantity_received.strip() or not payload.delivery_date.strip():
                raise HTTPException(status_code=422, detail="LR number, quantity, and date are required before verification")
            if payload.lr_number.strip().upper() != trip["lr_number"].upper():
                raise HTTPException(status_code=422, detail="Correct the LR number to match the trip")
            db.execute("UPDATE trips SET status='verified',remarks=?,pod_at=COALESCE(pod_at,?),ai_result=? WHERE id=?", (payload.shortage_or_damage_remarks.strip() or "Human verified", iso(utc_now()), json.dumps(result), trip_id))
            log_action(db, user, "human_verified", trip_id, payload.correction_note or "")
        updated = get_trip(db, trip_id)
    return trip_json(updated)


@app.get("/api/dashboard")
def dashboard(user: dict[str, Any] = Depends(require_role("billing"))) -> dict[str, Any]:
    with connect() as db:
        rows = db.execute("SELECT * FROM trips ORDER BY branch,id").fetchall()
    missing = [row for row in rows if row["status"] in {"missing", "retake_requested", "needs_review"}]
    delays: list[float] = []
    for row in rows:
        if row["pod_at"] and row["delivered_at"]:
            delivered = datetime.fromisoformat(row["delivered_at"])
            pod_at = datetime.fromisoformat(row["pod_at"])
            delays.append(max(0, (pod_at - delivered).total_seconds() / 86400))
    invoice_delays = []
    for row in rows:
        if row["invoice_at"] and row["pod_at"]:
            invoice_delays.append(max(0, (datetime.fromisoformat(row["invoice_at"]) - datetime.fromisoformat(row["pod_at"])).total_seconds() / 86400))
    branches: dict[str, dict[str, int]] = {}
    for row in rows:
        stat = branches.setdefault(row["branch"], {"trips": 0, "missing": 0, "review": 0})
        stat["trips"] += 1
        stat["missing"] += int(row["status"] == "missing")
        stat["review"] += int(row["status"] in {"retake_requested", "needs_review"})
    return {
        "total_trips": len(rows),
        "without_pod": sum(row["status"] in {"missing", "retake_requested", "needs_review"} for row in rows),
        "review_count": sum(row["status"] in {"retake_requested", "needs_review"} for row in rows),
        "verified_count": sum(row["status"] == "verified" for row in rows),
        "avg_delivery_to_pod_days": round(sum(delays) / len(delays), 1) if delays else None,
        "avg_pod_to_invoice_days": round(sum(invoice_delays) / len(invoice_delays), 1) if invoice_delays else None,
        "branches": branches,
        "missing_trips": [trip_json(row) for row in missing],
    }


@app.get("/api/review-queue")
def review_queue(user: dict[str, Any] = Depends(require_role("billing"))) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM trips WHERE status IN ('needs_review','retake_requested') ORDER BY delivered_at").fetchall()
    return [trip_json(row) for row in rows]


@app.get("/api/billing-queue")
def billing_queue(user: dict[str, Any] = Depends(require_role("billing"))) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM trips WHERE status='verified' AND invoice_at IS NULL ORDER BY pod_at").fetchall()
    return [trip_json(row) for row in rows]


@app.get("/api/billing/export.csv")
def export_billing(request: Request, user: dict[str, Any] = Depends(require_role("billing"))) -> StreamingResponse:
    with connect() as db:
        rows = db.execute("SELECT * FROM trips WHERE status='verified' AND invoice_at IS NULL ORDER BY client,id").fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Trip ID", "Client", "Vehicle", "LR Number", "E-way Bill", "Destination", "Freight INR", "POD Image", "POD Captured At"])
        for row in rows:
            writer.writerow([row["id"], row["client"], row["vehicle"], row["lr_number"], row["eway_bill"], row["destination"], row["freight"], urljoin(str(request.base_url), f"api/share/{row['share_token']}/image") if row["pod_image"] else "", row["pod_at"] or ""])
        for row in rows:
            log_action(db, user, "tally_exported", row["id"], "CSV export")
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=fleetpod-tally-export.csv"})


@app.post("/api/trips/{trip_id}/invoice")
def mark_invoiced(trip_id: str, user: dict[str, Any] = Depends(require_role("billing"))) -> dict[str, Any]:
    with connect() as db:
        trip = get_trip(db, trip_id)
        if trip["status"] != "verified":
            raise HTTPException(status_code=409, detail="Only verified PODs can be invoiced")
        db.execute("UPDATE trips SET invoice_at=? WHERE id=?", (iso(utc_now()), trip_id))
        log_action(db, user, "invoice_marked", trip_id)
        updated = get_trip(db, trip_id)
    return trip_json(updated)


@app.post("/api/trips/{trip_id}/upload-link")
def create_upload_link(trip_id: str, user: dict[str, Any] = Depends(require_role("billing"))) -> dict[str, str]:
    token = secrets.token_urlsafe(24)
    expires_at = iso(utc_now() + timedelta(days=1))
    with connect() as db:
        get_trip(db, trip_id)
        db.execute("INSERT INTO upload_links(token,trip_id,expires_at) VALUES(?,?,?)", (token, trip_id, expires_at))
        log_action(db, user, "sms_upload_link_created", trip_id, "Mock SMS link")
    return {"url": f"/upload/{token}", "message": "Mock SMS upload link created (valid for 24 hours)"}


@app.get("/api/share/{token}")
def shared_trip(token: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM trips WHERE share_token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="This client POD link is no longer available")
    result = trip_json(row)
    result["pod_url"] = f"/api/share/{token}/image" if row["pod_image"] else None
    return {key: value for key, value in result.items() if key not in {"share_token", "ai_result", "share_url", "vehicle", "pod_image"}}


@app.get("/api/upload-link/{token}")
def upload_link_details(token: str) -> dict[str, Any]:
    with connect() as db:
        link = db.execute("SELECT * FROM upload_links WHERE token=? AND used_at IS NULL", (token,)).fetchone()
        if not link or datetime.fromisoformat(link["expires_at"]) < utc_now():
            raise HTTPException(status_code=404, detail="This upload link has expired")
        trip = get_trip(db, link["trip_id"])
    return {"id": trip["id"], "client": trip["client"], "destination": trip["destination"], "lr_number": trip["lr_number"]}


@app.post("/api/upload-link/{token}/pod")
async def upload_via_link(token: str, payload: PodInput) -> dict[str, Any]:
    image_bytes, mime_type = validate_data_image(payload.image_data)
    try:
        captured_at = datetime.fromisoformat(payload.captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Capture time is invalid") from exc
    with connect() as db:
        link = db.execute("SELECT * FROM upload_links WHERE token=? AND used_at IS NULL", (token,)).fetchone()
        if not link or datetime.fromisoformat(link["expires_at"]) < utc_now():
            raise HTTPException(status_code=404, detail="This upload link has expired")
        trip_id = link["trip_id"]
        trip = get_trip(db, trip_id)
        if trip["status"] == "verified":
            raise HTTPException(status_code=409, detail="This trip already has a verified POD")
        trip_context = dict(trip)
        retake_count = trip["retake_count"] + (1 if trip["status"] == "retake_requested" else 0)
        db.execute("UPDATE upload_links SET used_at=? WHERE token=?", (iso(utc_now()), token))
    filename = f"{trip_id.lower()}-{secrets.token_hex(8)}.jpg"
    with connect() as db:
        db.execute("UPDATE trips SET status='uploaded',pod_image=?,pod_image_data=?,pod_at=?,remarks='AI check in progress',ai_result=NULL WHERE id=?", (filename, image_bytes, iso(captured_at), trip_id))
    status, reason, result = await evaluate_pod(image_bytes, mime_type, trip_context, retake_count)
    if status == "retake_requested":
        status, reason = "needs_review", "Hired-driver uploads go to a billing executive for any retake decision"
    with connect() as db:
        db.execute("UPDATE trips SET status=?,remarks=?,ai_result=? WHERE id=?", (status, reason, json.dumps(result) if result else None, trip_id))
        db.execute("INSERT INTO audit_log(actor_email,action,trip_id,detail,created_at) VALUES(?,?,?,?,?)", ("sms-link", "pod_uploaded", trip_id, f"Mock hired-driver link · GPS {payload.latitude},{payload.longitude}", iso(utc_now())))
        db.execute("INSERT INTO audit_log(actor_email,action,trip_id,detail,created_at) VALUES(?,?,?,?,?)", ("vision-check", "ai_checked" if result else "ai_unavailable", trip_id, reason, iso(utc_now())))
        updated = get_trip(db, trip_id)
    return trip_json(updated)


@app.get("/api/audit-log")
def audit_log(user: dict[str, Any] = Depends(require_role("billing"))) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT actor_email,action,trip_id,detail,created_at FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]

