"""Pure sqlite3 database schema initialization, connection management, and CRUD helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import get_db_path
from app.services.ingredient_parser import compute_ingredient_hash, normalize_ingredients


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    """Return current UTC date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().isoformat()


def generate_id(prefix: str) -> str:
    """Generate a compact readable identifier with a domain prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    upc TEXT UNIQUE,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT,
    certifier_name TEXT,
    certifier_status TEXT,
    kosher_symbol TEXT,
    is_certified_vegan INTEGER NOT NULL DEFAULT 0,
    brand_contact_email TEXT,
    brand_contact_url TEXT,
    computed_status TEXT NOT NULL DEFAULT 'mushbooh_needs_check',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_upc ON products(upc);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(LOWER(brand));
CREATE INDEX IF NOT EXISTS idx_products_status ON products(computed_status);

CREATE TABLE IF NOT EXISTS formulation_snapshots (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    raw_ingredients TEXT NOT NULL,
    normalized_ingredients TEXT NOT NULL,
    ingredient_hash TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'manual',
    lot_code TEXT,
    plant_code TEXT,
    captured_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_snapshots_product_current
    ON formulation_snapshots(product_id, is_current, captured_at);

CREATE TABLE IF NOT EXISTS ingredient_rules (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    default_risk TEXT NOT NULL,
    us_context_notes TEXT NOT NULL,
    verification_question TEXT NOT NULL,
    kosher_vegan_caveat TEXT NOT NULL,
    strictness_key TEXT
);

CREATE TABLE IF NOT EXISTS brand_policies (
    id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    scope_description TEXT NOT NULL,
    applies_to_ingredients_json TEXT NOT NULL DEFAULT '[]',
    determination TEXT NOT NULL,
    source_url TEXT,
    excerpt TEXT NOT NULL,
    checked_date TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_brand_policies_brand ON brand_policies(LOWER(brand));

CREATE TABLE IF NOT EXISTS company_verifications (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    formulation_snapshot_id TEXT NOT NULL REFERENCES formulation_snapshots(id) ON DELETE CASCADE,
    ingredient_name TEXT NOT NULL,
    determination TEXT NOT NULL,
    varies_by_supplier INTEGER NOT NULL DEFAULT 0,
    contact_channel TEXT NOT NULL DEFAULT 'email',
    company_contact TEXT,
    response_excerpt TEXT NOT NULL,
    lot_code TEXT,
    plant_code TEXT,
    verified_date TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verifications_product
    ON company_verifications(product_id, verified_date);

CREATE TABLE IF NOT EXISTS outreach_inquiries (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    formulation_snapshot_id TEXT NOT NULL REFERENCES formulation_snapshots(id) ON DELETE CASCADE,
    target_email TEXT,
    flagged_ingredients_json TEXT NOT NULL DEFAULT '[]',
    generated_subject TEXT NOT NULL,
    generated_body TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'full_inquiry',
    state TEXT NOT NULL DEFAULT 'drafted',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outreach_product
    ON outreach_inquiries(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_outreach_state
    ON outreach_inquiries(state, updated_at);

CREATE TABLE IF NOT EXISTS forum_signals (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    source_platform TEXT NOT NULL,
    source_name TEXT NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    author TEXT,
    posted_at TEXT,
    raw_excerpt TEXT NOT NULL,
    matched_ingredients_json TEXT NOT NULL DEFAULT '[]',
    claimed_determination TEXT NOT NULL,
    evidence_tier TEXT NOT NULL,
    freshness TEXT NOT NULL,
    region_flag TEXT NOT NULL,
    region_notes TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forum_signals_product
    ON forum_signals(product_id, fetched_at);

CREATE TABLE IF NOT EXISTS community_notes (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    author_label TEXT NOT NULL,
    note_text TEXT NOT NULL,
    confidence_tier TEXT NOT NULL DEFAULT 'secondary_observation',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_community_notes_product
    ON community_notes(product_id, created_at);

CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection with Row factory and foreign keys enabled."""
    target = str(db_path) if db_path is not None else str(get_db_path())
    if target != ":memory:":
        path_obj = Path(target)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def db_session(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a SQLite connection with commit/rollback handling."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency yielding a SQLite connection per request."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    """Execute DDL schema statements on an already-open SQLite connection."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)


def init_db(db_path: str | Path | sqlite3.Connection | None = None) -> None:
    """Initialize all HalalLens database tables and indexes idempotently."""
    if isinstance(db_path, sqlite3.Connection):
        init_schema(db_path)
        db_path.commit()
        return

    with db_session(db_path) as conn:
        init_schema(conn)


# ---------------------------------------------------------------------------
# Query & CRUD Helpers
# ---------------------------------------------------------------------------


def normalize_upc(upc: str | None) -> str | None:
    """Strip non-digit formatting from a UPC/EAN barcode string."""
    if upc is None:
        return None
    digits = "".join(ch for ch in upc.strip() if ch.isdigit())
    return digits or upc.strip() or None


def count_products(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()
    return int(row["cnt"]) if row else 0


def fetch_product_row(conn: sqlite3.Connection, product_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()


def fetch_product_by_upc(conn: sqlite3.Connection, upc: str) -> sqlite3.Row | None:
    """Lookup product by exact UPC or normalized leading-zero variant (UPC-A / EAN-13)."""
    cleaned = normalize_upc(upc)
    if not cleaned:
        return None

    row = conn.execute(
        "SELECT * FROM products WHERE upc = ?",
        (cleaned,),
    ).fetchone()
    if row is not None:
        return row

    # Try 12-digit UPC-A / 13-digit EAN-13 leading-zero normalization.
    candidates: set[str] = {cleaned}
    stripped = cleaned.lstrip("0")
    if stripped:
        candidates.add(stripped)
        if len(stripped) <= 12:
            candidates.add(stripped.zfill(12))
        if len(stripped) <= 13:
            candidates.add(stripped.zfill(13))
        if len(stripped) <= 8:
            candidates.add(stripped.zfill(8))

    placeholders = ",".join("?" for _ in candidates)
    return conn.execute(
        f"SELECT * FROM products WHERE upc IN ({placeholders}) LIMIT 1",
        tuple(candidates),
    ).fetchone()


def list_product_rows(
    conn: sqlite3.Connection,
    q: str | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []

    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(name) LIKE ? OR LOWER(brand) LIKE ? OR LOWER(COALESCE(upc, '')) LIKE ? OR LOWER(COALESCE(category, '')) LIKE ?)"
        )
        params.extend([like, like, like, like])

    if status and status.strip():
        clauses.append("computed_status = ?")
        params.append(status.strip())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"SELECT * FROM products {where_sql} ORDER BY updated_at DESC, name ASC",
            tuple(params),
        ).fetchall()
    )


def insert_product_with_snapshot(
    conn: sqlite3.Connection,
    *,
    name: str,
    brand: str,
    raw_ingredients: str,
    upc: str | None = None,
    category: str | None = None,
    source_type: str = "manual",
    certifier_name: str | None = None,
    certifier_status: str | None = None,
    kosher_symbol: str | None = None,
    is_certified_vegan: bool = False,
    brand_contact_email: str | None = None,
    brand_contact_url: str | None = None,
    lot_code: str | None = None,
    plant_code: str | None = None,
    product_id: str | None = None,
    snapshot_id: str | None = None,
    captured_at: str | None = None,
) -> tuple[str, str]:
    """Create a product and its initial current formulation snapshot."""
    now = captured_at or utc_now_iso()
    pid = product_id or generate_id("prod")
    sid = snapshot_id or generate_id("snap")
    cleaned_upc = normalize_upc(upc)
    normalized_ing = normalize_ingredients(raw_ingredients)
    ing_hash = compute_ingredient_hash(raw_ingredients)

    conn.execute(
        """
        INSERT INTO products (
            id, upc, name, brand, category, certifier_name, certifier_status,
            kosher_symbol, is_certified_vegan, brand_contact_email, brand_contact_url,
            computed_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pid,
            cleaned_upc,
            name.strip(),
            brand.strip(),
            category.strip() if category else None,
            certifier_name.strip() if certifier_name else None,
            certifier_status.strip() if certifier_status else None,
            kosher_symbol.strip() if kosher_symbol else None,
            1 if is_certified_vegan else 0,
            brand_contact_email.strip() if brand_contact_email else None,
            brand_contact_url.strip() if brand_contact_url else None,
            "mushbooh_needs_check",
            now,
            now,
        ),
    )

    conn.execute(
        """
        INSERT INTO formulation_snapshots (
            id, product_id, raw_ingredients, normalized_ingredients,
            ingredient_hash, source_type, lot_code, plant_code, captured_at, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            sid,
            pid,
            raw_ingredients.strip(),
            normalized_ing,
            ing_hash,
            source_type,
            lot_code,
            plant_code,
            now,
        ),
    )

    return pid, sid


def add_formulation_snapshot(
    conn: sqlite3.Connection,
    product_id: str,
    raw_ingredients: str,
    *,
    source_type: str = "manual",
    lot_code: str | None = None,
    plant_code: str | None = None,
    snapshot_id: str | None = None,
    captured_at: str | None = None,
) -> sqlite3.Row:
    """Append a new current formulation snapshot and demote previous current snapshots."""
    now = captured_at or utc_now_iso()
    sid = snapshot_id or generate_id("snap")
    normalized_ing = normalize_ingredients(raw_ingredients)
    ing_hash = compute_ingredient_hash(raw_ingredients)

    conn.execute(
        "UPDATE formulation_snapshots SET is_current = 0 WHERE product_id = ?",
        (product_id,),
    )
    conn.execute(
        """
        INSERT INTO formulation_snapshots (
            id, product_id, raw_ingredients, normalized_ingredients,
            ingredient_hash, source_type, lot_code, plant_code, captured_at, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            sid,
            product_id,
            raw_ingredients.strip(),
            normalized_ing,
            ing_hash,
            source_type,
            lot_code,
            plant_code,
            now,
        ),
    )
    conn.execute(
        "UPDATE products SET updated_at = ? WHERE id = ?",
        (now, product_id),
    )
    row = conn.execute(
        "SELECT * FROM formulation_snapshots WHERE id = ?",
        (sid,),
    ).fetchone()
    assert row is not None
    return row


def fetch_snapshots_for_product(
    conn: sqlite3.Connection,
    product_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM formulation_snapshots
            WHERE product_id = ?
            ORDER BY is_current DESC, captured_at DESC, rowid DESC
            """,
            (product_id,),
        ).fetchall()
    )


def fetch_snapshot_by_id(
    conn: sqlite3.Connection,
    snapshot_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM formulation_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()


def fetch_all_ingredient_rules(
    conn: sqlite3.Connection,
    q: str | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM ingredient_rules ORDER BY canonical_name COLLATE NOCASE ASC"
    ).fetchall()
    results: list[dict[str, Any]] = []
    q_norm = q.strip().lower() if q and q.strip() else None

    for row in rows:
        aliases = json.loads(row["aliases_json"] or "[]")
        item = {
            "id": row["id"],
            "canonical_name": row["canonical_name"],
            "aliases": aliases,
            "default_risk": row["default_risk"],
            "us_context_notes": row["us_context_notes"],
            "verification_question": row["verification_question"],
            "kosher_vegan_caveat": row["kosher_vegan_caveat"],
            "strictness_key": row["strictness_key"],
        }
        if q_norm:
            haystack = " ".join(
                [
                    item["canonical_name"],
                    " ".join(aliases),
                    item["us_context_notes"],
                ]
            ).lower()
            if q_norm not in haystack:
                continue
        results.append(item)
    return results


def fetch_brand_policies(
    conn: sqlite3.Connection,
    brand: str | None = None,
) -> list[dict[str, Any]]:
    if brand and brand.strip():
        rows = conn.execute(
            "SELECT * FROM brand_policies ORDER BY checked_date DESC, created_at DESC"
        ).fetchall()
        brand_lower = brand.strip().lower()
        filtered: list[sqlite3.Row] = []
        exact: list[sqlite3.Row] = []
        for row in rows:
            p_brand = row["brand"].strip().lower()
            if p_brand == brand_lower:
                exact.append(row)
            elif p_brand in brand_lower or brand_lower in p_brand:
                filtered.append(row)
        rows = exact + filtered
    else:
        rows = conn.execute(
            "SELECT * FROM brand_policies ORDER BY brand COLLATE NOCASE ASC, checked_date DESC"
        ).fetchall()

    return [
        {
            "id": row["id"],
            "brand": row["brand"],
            "scope_description": row["scope_description"],
            "applies_to_ingredients": json.loads(row["applies_to_ingredients_json"] or "[]"),
            "determination": row["determination"],
            "source_url": row["source_url"],
            "excerpt": row["excerpt"],
            "checked_date": row["checked_date"],
            "expires_at": row["expires_at"],
        }
        for row in rows
    ]


def insert_brand_policy(
    conn: sqlite3.Connection,
    *,
    brand: str,
    scope_description: str,
    applies_to_ingredients: list[str],
    determination: str,
    excerpt: str,
    source_url: str | None = None,
    checked_date: str | None = None,
    expires_at: str | None = None,
    policy_id: str | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    pid = policy_id or generate_id("bp")
    c_date = checked_date or today_iso()
    conn.execute(
        """
        INSERT INTO brand_policies (
            id, brand, scope_description, applies_to_ingredients_json,
            determination, source_url, excerpt, checked_date, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pid,
            brand.strip(),
            scope_description.strip(),
            json.dumps(applies_to_ingredients),
            determination,
            source_url.strip() if source_url else None,
            excerpt.strip(),
            c_date,
            expires_at,
            now,
        ),
    )
    return {
        "id": pid,
        "brand": brand.strip(),
        "scope_description": scope_description.strip(),
        "applies_to_ingredients": applies_to_ingredients,
        "determination": determination,
        "source_url": source_url.strip() if source_url else None,
        "excerpt": excerpt.strip(),
        "checked_date": c_date,
        "expires_at": expires_at,
    }


def fetch_verifications_for_product(
    conn: sqlite3.Connection,
    product_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM company_verifications
            WHERE product_id = ?
            ORDER BY verified_date DESC, created_at DESC, rowid DESC
            """,
            (product_id,),
        ).fetchall()
    )


def insert_verification(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    formulation_snapshot_id: str,
    ingredient_name: str,
    determination: str,
    response_excerpt: str,
    varies_by_supplier: bool = False,
    contact_channel: str = "email",
    company_contact: str | None = None,
    lot_code: str | None = None,
    plant_code: str | None = None,
    verified_date: str | None = None,
    expires_at: str | None = None,
    verification_id: str | None = None,
) -> str:
    now = utc_now_iso()
    vid = verification_id or generate_id("ver")
    v_date = verified_date or today_iso()

    conn.execute(
        """
        INSERT INTO company_verifications (
            id, product_id, formulation_snapshot_id, ingredient_name, determination,
            varies_by_supplier, contact_channel, company_contact, response_excerpt,
            lot_code, plant_code, verified_date, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vid,
            product_id,
            formulation_snapshot_id,
            ingredient_name.strip(),
            determination,
            1 if varies_by_supplier else 0,
            contact_channel,
            company_contact.strip() if company_contact else None,
            response_excerpt.strip(),
            lot_code,
            plant_code,
            v_date,
            expires_at,
            now,
        ),
    )
    conn.execute(
        "UPDATE products SET updated_at = ? WHERE id = ?",
        (now, product_id),
    )
    return vid


def fetch_outreach_for_product(
    conn: sqlite3.Connection,
    product_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM outreach_inquiries
            WHERE product_id = ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (product_id,),
        ).fetchall()
    )


def fetch_outreach_by_id(
    conn: sqlite3.Connection,
    inquiry_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM outreach_inquiries WHERE id = ?",
        (inquiry_id,),
    ).fetchone()


def fetch_all_pending_outreach(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT oi.*, p.name AS product_name, p.brand AS brand,
                   p.upc AS upc, p.computed_status AS computed_status
            FROM outreach_inquiries oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.state IN ('drafted', 'sent_by_user')
            ORDER BY oi.updated_at DESC, oi.rowid DESC
            """
        ).fetchall()
    )


def insert_outreach_inquiry(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    formulation_snapshot_id: str,
    target_email: str | None,
    flagged_ingredients: list[str],
    generated_subject: str,
    generated_body: str,
    mode: str = "full_inquiry",
    state: str = "drafted",
    inquiry_id: str | None = None,
    created_at: str | None = None,
) -> sqlite3.Row:
    now = created_at or utc_now_iso()
    oid = inquiry_id or generate_id("out")
    conn.execute(
        """
        INSERT INTO outreach_inquiries (
            id, product_id, formulation_snapshot_id, target_email,
            flagged_ingredients_json, generated_subject, generated_body,
            mode, state, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            oid,
            product_id,
            formulation_snapshot_id,
            target_email,
            json.dumps(flagged_ingredients),
            generated_subject,
            generated_body,
            mode,
            state,
            now,
            now,
        ),
    )
    row = fetch_outreach_by_id(conn, oid)
    assert row is not None
    return row


def update_outreach_state(
    conn: sqlite3.Connection,
    inquiry_id: str,
    state: str,
) -> sqlite3.Row | None:
    now = utc_now_iso()
    cur = conn.execute(
        "UPDATE outreach_inquiries SET state = ?, updated_at = ? WHERE id = ?",
        (state, now, inquiry_id),
    )
    if cur.rowcount == 0:
        return None
    return fetch_outreach_by_id(conn, inquiry_id)


def fetch_forum_signals_for_product(
    conn: sqlite3.Connection,
    product_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM forum_signals
            WHERE product_id = ?
            ORDER BY COALESCE(posted_at, '') DESC, fetched_at DESC, rowid DESC
            """,
            (product_id,),
        ).fetchall()
    )


def fetch_forum_signal_by_id(
    conn: sqlite3.Connection,
    signal_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM forum_signals WHERE id = ?",
        (signal_id,),
    ).fetchone()


def insert_forum_signal(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    source_platform: str,
    source_name: str,
    title: str,
    raw_excerpt: str,
    matched_ingredients: list[str],
    claimed_determination: str,
    evidence_tier: str,
    freshness: str,
    region_flag: str,
    url: str | None = None,
    author: str | None = None,
    posted_at: str | None = None,
    region_notes: str | None = None,
    fetched_at: str | None = None,
    signal_id: str | None = None,
) -> str:
    now = fetched_at or utc_now_iso()
    fid = signal_id or generate_id("fs")
    conn.execute(
        """
        INSERT INTO forum_signals (
            id, product_id, source_platform, source_name, url, title, author,
            posted_at, raw_excerpt, matched_ingredients_json,
            claimed_determination, evidence_tier, freshness, region_flag,
            region_notes, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fid,
            product_id,
            source_platform,
            source_name,
            url,
            title,
            author,
            posted_at,
            raw_excerpt,
            json.dumps(matched_ingredients),
            claimed_determination,
            evidence_tier,
            freshness,
            region_flag,
            region_notes,
            now,
        ),
    )
    return fid


def fetch_community_notes_for_product(
    conn: sqlite3.Connection,
    product_id: str,
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM community_notes
            WHERE product_id = ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (product_id,),
        ).fetchall()
    )


def insert_community_note(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    author_label: str,
    note_text: str,
    confidence_tier: str = "secondary_observation",
    note_id: str | None = None,
    created_at: str | None = None,
) -> sqlite3.Row:
    now = created_at or utc_now_iso()
    nid = note_id or generate_id("note")
    conn.execute(
        """
        INSERT INTO community_notes (
            id, product_id, author_label, note_text, confidence_tier, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            nid,
            product_id,
            author_label.strip() or "Personal Note",
            note_text.strip(),
            confidence_tier,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM community_notes WHERE id = ?",
        (nid,),
    ).fetchone()
    assert row is not None
    return row


def get_setting(
    conn: sqlite3.Connection,
    key: str,
    default: Any = None,
) -> Any:
    row = conn.execute(
        "SELECT value_json FROM user_settings WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return default
    return json.loads(row["value_json"])


def set_setting(
    conn: sqlite3.Connection,
    key: str,
    value: Any,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO user_settings (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (key, json.dumps(value), now),
    )
