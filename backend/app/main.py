"""HalalLens FastAPI entrypoint, database lifespan seeding, CORS, healthcheck, and SPA hosting."""

from __future__ import annotations

import base64
import hmac
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.routers import analysis, forums, products, verification
from app.schemas import HealthResponse
from app.seed import seed_database

FRONTEND_DIST_DIR: Path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _extract_passcode(request: Request) -> str | None:
    header_code = request.headers.get("x-passcode")
    if header_code:
        return header_code.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
            return decoded.split(":", 1)[-1]
        except Exception:
            return None
    return None


def _is_passcode_valid(request: Request, expected: str) -> bool:
    provided = _extract_passcode(request)
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize SQLite schema and idempotently seed U.S. rules and prototype products."""
    db.init_db()
    with db.db_session() as conn:
        seed_database(conn)
    yield


app = FastAPI(
    title="HalalLens API",
    version="0.2.0",
    description="U.S. Grocery Barcode & Ingredient Verification API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def passcode_guard(request: Request, call_next):
    """Protect /api/* when HALAL_SCAN_PASSCODE is configured, leaving health/auth endpoints open."""
    expected = config.get_passcode()
    path = request.url.path
    if (
        expected
        and request.method != "OPTIONS"
        and path.startswith("/api/")
        and path not in {"/api/health", "/api/auth/status"}
        and not _is_passcode_valid(request, expected)
    ):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Passcode required to access this HalalLens instance."},
        )
    return await call_next(request)


app.include_router(products.router)
app.include_router(verification.router)
app.include_router(analysis.router)
app.include_router(forums.router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def healthcheck(conn: sqlite3.Connection = Depends(db.get_db)) -> HealthResponse:
    """Health check confirming SQLite readiness and catalog count."""
    return HealthResponse(
        status="ok",
        db="ready",
        products_count=db.count_products(conn),
    )


@app.get("/api/auth/status", tags=["system"])
def auth_status(request: Request) -> dict[str, bool]:
    """Report whether personal-mode passcode protection is active and satisfied."""
    expected = config.get_passcode()
    if not expected:
        return {"passcode_required": False, "authenticated": True}
    return {
        "passcode_required": True,
        "authenticated": _is_passcode_valid(request, expected),
    }


if FRONTEND_DIST_DIR.is_dir() and (FRONTEND_DIST_DIR / "index.html").is_file():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    _dist_root = FRONTEND_DIST_DIR.resolve()
    _index_file = _dist_root / "index.html"

    @app.get("/", include_in_schema=False)
    def serve_spa_root() -> FileResponse:
        return FileResponse(str(_index_file))

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa_fallback(full_path: str) -> FileResponse:
        # Never swallow unknown /api/* routes with HTML; always return JSON 404.
        normalized = full_path.lstrip("/")
        if normalized == "api" or normalized.startswith("api/"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API endpoint not found.",
            )

        if normalized:
            candidate = (_dist_root / normalized).resolve()
            if _dist_root in candidate.parents and candidate.is_file():
                return FileResponse(str(candidate))

        return FileResponse(str(_index_file))
