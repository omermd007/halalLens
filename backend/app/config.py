"""Configuration settings and environment overrides for HalalLens backend."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH: Path = BASE_DIR / "data" / "halal_scan.db"


def get_db_path() -> Path:
    """Resolve the active SQLite database path, honoring HALAL_SCAN_DB_PATH."""
    override = os.getenv("HALAL_SCAN_DB_PATH")
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_PATH


DB_PATH: Path = get_db_path()
USDA_API_KEY: str = os.getenv("USDA_API_KEY", "DEMO_KEY")
REDDIT_USER_AGENT: str = os.getenv(
    "REDDIT_USER_AGENT",
    "HalalLens/0.1 (U.S. Grocery Ingredient Verification Prototype)",
)
COOLDOWN_PRODUCT_DAYS: int = int(os.getenv("COOLDOWN_PRODUCT_DAYS", "30"))
COOLDOWN_BRAND_DAYS: int = int(os.getenv("COOLDOWN_BRAND_DAYS", "14"))
EXPIRING_SOON_DAYS: int = int(os.getenv("EXPIRING_SOON_DAYS", "30"))


def get_passcode() -> str | None:
    """Return optional personal-mode passcode from HALAL_SCAN_PASSCODE, or None if open."""
    val = os.getenv("HALAL_SCAN_PASSCODE", "").strip()
    return val or None


def should_seed_examples() -> bool:
    """Return False when HALAL_SCAN_SEED_EXAMPLES is explicitly disabled (0/false/no)."""
    val = os.getenv("HALAL_SCAN_SEED_EXAMPLES", "true").strip().lower()
    return val not in {"0", "false", "no", "off"}


def get_cors_origins() -> list[str]:
    """Return allowed CORS origins, combining local dev defaults with CORS_ALLOW_ORIGINS."""
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    extra = os.getenv("CORS_ALLOW_ORIGINS", "")
    for item in extra.split(","):
        origin = item.strip().rstrip("/")
        if origin and origin not in defaults:
            defaults.append(origin)
    return defaults
