"""Tests for optional personal-mode passcode guard and clean-seed configuration."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.seed import seed_database


def test_passcode_disabled_by_default(client: TestClient) -> None:
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    assert res.json() == {"passcode_required": False, "authenticated": True}
    assert client.get("/api/products").status_code == 200


def test_passcode_protects_api_routes_when_enabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("HALAL_SCAN_PASSCODE", "salam-2026")

    # Health and auth status remain reachable
    assert client.get("/api/health").status_code == 200
    status_res = client.get("/api/auth/status")
    assert status_res.status_code == 200
    assert status_res.json() == {"passcode_required": True, "authenticated": False}

    # Protected API rejects missing or wrong passcode
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/products", headers={"X-Passcode": "wrong"}).status_code == 401

    # Accepts X-Passcode header
    ok_res = client.get("/api/products", headers={"X-Passcode": "salam-2026"})
    assert ok_res.status_code == 200
    assert client.get("/api/auth/status", headers={"X-Passcode": "salam-2026"}).json() == {
        "passcode_required": True,
        "authenticated": True,
    }

    # Accepts Bearer and HTTP Basic too
    assert client.get("/api/products", headers={"Authorization": "Bearer salam-2026"}).status_code == 200
    basic = base64.b64encode(b"owner:salam-2026").decode("ascii")
    assert client.get("/api/products", headers={"Authorization": f"Basic {basic}"}).status_code == 200


def test_clean_seed_without_examples(tmp_path: Path) -> None:
    clean_db = tmp_path / "clean.db"
    db.init_db(clean_db)
    with db.db_session(clean_db) as conn:
        seed_database(conn, include_examples=False)
        assert db.count_products(conn) == 0
        rules_count = conn.execute("SELECT COUNT(*) FROM ingredient_rules").fetchone()[0]
        assert rules_count >= 16
