"""Shared pytest fixtures providing isolated temporary SQLite databases and TestClient."""

from __future__ import annotations

import sqlite3
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=".*httpx.*starlette\\.testclient.*",
        category=UserWarning,
    )
    from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_database  # noqa: E402


@pytest.fixture()
def isolated_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HALAL_SCAN_DB_PATH to an isolated per-test SQLite file in tmp_path."""
    db_file = tmp_path / "test_halal_scan.db"
    monkeypatch.setenv("HALAL_SCAN_DB_PATH", str(db_file))
    return db_file


@pytest.fixture()
def seeded_conn(isolated_db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield an initialized, seeded SQLite connection backed by the isolated test DB."""
    db.init_db(isolated_db_path)
    conn = db.get_connection(isolated_db_path)
    try:
        seed_database(conn)
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def client(isolated_db_path: Path) -> Iterator[TestClient]:
    """Yield a FastAPI TestClient running full lifespan seeding on an isolated DB."""
    with TestClient(app) as test_client:
        yield test_client
