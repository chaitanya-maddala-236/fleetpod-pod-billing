import base64
import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as fleetpod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(fleetpod, "DATABASE_PATH", tmp_path / "fleetpod-test.db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fleetpod.initialize_database()
    with TestClient(fleetpod.app) as test_client:
        yield test_client


def sign_in(client, role="billing"):
    credentials = {
        "billing": ("billing@fleetpod.demo", "BillingDemo26!"),
        "driver": ("driver@fleetpod.demo", "DriverDemo26!"),
    }[role]
    response = client.post("/api/login", json={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 200
    return response.json()


def photo_payload():
    image = Image.new("RGB", (480, 360), "#f5f4ef")
    image.putpixel((1, 1), (10, 20, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    return {
        "image_data": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "latitude": 19.876,
        "longitude": 75.343,
    }


def test_health_and_role_access(client):
    assert client.get("/api/health").json()["status"] == "ok"
    home = client.get("/")
    assert home.status_code == 200
    assert "FleetPOD" in home.text
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert client.get("/api/trips").status_code == 401
    sign_in(client, "driver")
    assert client.get("/api/review-queue").status_code == 403
    assert client.get("/api/trips").status_code == 200


def test_photo_upload_without_ai_goes_to_human_review(client):
    sign_in(client, "driver")
    response = client.post("/api/trips/TRP-66152/pod", json=photo_payload())
    assert response.status_code == 200
    trip = response.json()["trip"]
    assert trip["status"] == "needs_review"
    assert "not configured" in trip["remarks"]
    assert trip["pod_url"] == "/api/pods/TRP-66152/image"
    assert client.get(trip["pod_url"]).status_code == 200
    share_token = trip["share_url"].split("/")[-1]
    client.post("/api/logout")
    assert client.get(trip["pod_url"]).status_code == 401
    assert client.get(f"/api/share/{share_token}/image").status_code == 200


def test_vision_check_sends_shortage_to_billing_review():
    result = fleetpod.normalize_ai_result({
        "lr_number": "LR-66141",
        "consignee_stamp_visible": True,
        "quantity_received": "114 cartons",
        "shortage_or_damage_remarks": "Short by 6 cartons",
        "delivery_date": "2026-11-02",
        "signature_visible": True,
        "confidence": 0.99,
        "issues": [],
    }, {"lr_number": "LR-66141", "expected_qty": "120 cartons"})
    status, _ = fleetpod.decide_pod_status(result, {"lr_number": "LR-66141"})
    assert status == "needs_review"
    quantity_only = fleetpod.normalize_ai_result({
        "lr_number": "LR-66141", "consignee_stamp_visible": True,
        "quantity_received": "100 cartons", "shortage_or_damage_remarks": "",
        "delivery_date": "2026-11-02", "signature_visible": True,
        "confidence": 0.99, "issues": [],
    }, {"lr_number": "LR-66141", "expected_qty": "120 cartons"})
    assert quantity_only["quantity_mismatch"] is True
    assert fleetpod.decide_pod_status(quantity_only, {"lr_number": "LR-66141"})[0] == "needs_review"


def test_low_confidence_sends_driver_capture_to_retake():
    result = {
        "lr_number": "LR-66134", "consignee_stamp_visible": True,
        "quantity_received": "18 bundles", "shortage_or_damage_remarks": "",
        "delivery_date": "2026-11-02", "signature_visible": True,
        "confidence": 0.4, "issues": [],
    }
    status, reason = fleetpod.decide_pod_status(result, {"lr_number": "LR-66134"})
    assert status == "retake_requested"
    assert "confidence" in reason


def test_two_retake_limit_routes_unclear_pod_to_review(client, monkeypatch):
    sign_in(client, "driver")

    async def low_confidence(*_args, **_kwargs):
        return {
            "lr_number": "LR-66134", "consignee_stamp_visible": True,
            "quantity_received": "18 bundles", "shortage_or_damage_remarks": "",
            "delivery_date": "2026-11-02", "signature_visible": True,
            "confidence": 0.4, "issues": [],
        }

    monkeypatch.setattr(fleetpod, "vision_check", low_confidence)
    response = client.post("/api/trips/TRP-66134/pod", json=photo_payload())
    assert response.status_code == 200
    assert response.json()["trip"]["status"] == "needs_review"
    assert response.json()["trip"]["retake_count"] == 2
    assert "Two retakes" in response.json()["trip"]["remarks"]


def test_human_review_releases_verified_trip_to_export(client):
    sign_in(client, "billing")
    payload = {
        "action": "verify", "lr_number": "LR-66141", "quantity_received": "114 cartons",
        "delivery_date": "2026-11-02", "consignee_stamp_visible": True,
        "signature_visible": True, "shortage_or_damage_remarks": "Short by 6 cartons",
        "correction_note": "Confirmed shortage against signed POD",
    }
    response = client.post("/api/trips/TRP-66141/review", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    exported = client.get("/api/billing/export.csv")
    assert exported.status_code == 200
    assert "TRP-66141" in exported.text
    assert "EWB-2710-66141" in exported.text
    assert "/api/share/" in exported.text


def test_verified_pod_can_be_marked_invoiced_for_metric(client):
    sign_in(client, "billing")
    response = client.post("/api/trips/TRP-66120/invoice")
    assert response.status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["avg_pod_to_invoice_days"] is not None


def test_hired_driver_upload_link_is_one_time_and_routes_to_review(client):
    sign_in(client, "billing")
    response = client.post("/api/trips/TRP-66152/upload-link")
    assert response.status_code == 200
    token = response.json()["url"].split("/")[-1]
    assert client.get(f"/api/upload-link/{token}").status_code == 200
    upload = client.post(f"/api/upload-link/{token}/pod", json=photo_payload())
    assert upload.status_code == 200
    assert upload.json()["status"] == "needs_review"
    assert client.get(f"/api/upload-link/{token}").status_code == 404

