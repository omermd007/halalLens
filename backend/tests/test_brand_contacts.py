"""Tests for verified U.S. Brand Contact Directory, email/SSRF safety filters, and /api/brands/lookup-contact."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.services import brand_contacts


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_zero_example_com_placeholders_in_seeds_and_directory(seeded_conn) -> None:
    """Confirm zero @example.com emails remain in seed files, brandContacts.json, or seeded DB."""
    files_to_check = [
        REPO_ROOT / "frontend" / "src" / "engine" / "seeds.ts",
        REPO_ROOT / "frontend" / "src" / "data" / "brandContacts.json",
        REPO_ROOT / "backend" / "app" / "seed.py",
    ]
    for path in files_to_check:
        text = path.read_text(encoding="utf-8").lower()
        assert "example.com" not in text, f"Found example.com placeholder in {path}"

    # Verify seeded database rows have zero example.com contacts.
    for table, col in (
        ("products", "brand_contact_email"),
        ("company_verifications", "company_contact"),
        ("outreach_inquiries", "target_email"),
    ):
        rows = seeded_conn.execute(
            f"SELECT {col} FROM {table} WHERE LOWER(COALESCE({col}, '')) LIKE '%example.com%'"
        ).fetchall()
        assert rows == [], f"Found example.com in {table}.{col}: {rows}"


def test_verified_directory_coverage_and_schema() -> None:
    directory = brand_contacts.load_brand_directory()
    assert len(directory) >= 30

    for entry in directory:
        assert entry["brand"]
        assert isinstance(entry["aliases"], list) and len(entry["aliases"]) >= 1
        assert entry["contact_type"] in ("email", "web_form")
        assert str(entry["contact_url"]).startswith("https://")
        if entry["contact_type"] == "email":
            assert entry["email"] and "@" in entry["email"]
            assert brand_contacts.is_valid_support_email(entry["email"])
        else:
            assert entry["email"] is None


def test_directory_fuzzy_alias_matching() -> None:
    kraft = brand_contacts.lookup_directory_contact("Kraft")
    assert kraft is not None
    assert kraft["brand"] == "Kraft Heinz"
    assert kraft["contact_type"] == "web_form"
    assert kraft["email"] is None
    assert kraft["contact_url"] == "https://contactus.kraftheinz.com/en-us"

    oreo = brand_contacts.lookup_directory_contact("Oreo")
    assert oreo is not None
    assert oreo["brand"] == "Mondelēz International"
    assert oreo["contact_type"] == "web_form"

    annies = brand_contacts.lookup_directory_contact("Annie's Homegrown")
    assert annies is not None
    assert annies["brand"] == "General Mills"
    assert annies["contact_type"] == "web_form"

    goodles = brand_contacts.lookup_directory_contact("Goodles")
    assert goodles is not None
    assert goodles["contact_type"] == "email"
    assert goodles["email"] == "help@goodles.com"

    kirkland = brand_contacts.lookup_directory_contact("Kirkland Signature")
    assert kirkland is not None
    assert "Costco" in kirkland["brand"]

    # Word-boundary protection: "Compost Farms" must NOT match "Post".
    assert brand_contacts.lookup_directory_contact("Compost Farms") is None


def test_support_email_validation_filters() -> None:
    assert brand_contacts.is_valid_support_email("help@goodles.com", expected_domain="www.goodles.com")
    assert brand_contacts.is_valid_support_email("customerservice@saffronroad.com", expected_domain="saffronroad.com")

    # Reject placeholder / blocked domains.
    assert not brand_contacts.is_valid_support_email("support@example.com")
    assert not brand_contacts.is_valid_support_email("care@kraftheinz.example.com")
    assert not brand_contacts.is_valid_support_email("help@test.com")

    # Reject non-consumer-support local parts.
    assert not brand_contacts.is_valid_support_email("noreply@goodles.com", expected_domain="goodles.com")
    assert not brand_contacts.is_valid_support_email("no-reply@goodles.com", expected_domain="goodles.com")
    assert not brand_contacts.is_valid_support_email("privacy@goodles.com", expected_domain="goodles.com")
    assert not brand_contacts.is_valid_support_email("press@goodles.com", expected_domain="goodles.com")
    assert not brand_contacts.is_valid_support_email("ir@goodles.com", expected_domain="goodles.com")

    # Reject third-party domain mismatch when expected_domain is provided.
    assert not brand_contacts.is_valid_support_email("help@otherbrand.com", expected_domain="goodles.com")


def test_ssrf_url_guard_rejects_private_and_local_targets() -> None:
    assert not brand_contacts._is_safe_public_url("http://127.0.0.1/contact")
    assert not brand_contacts._is_safe_public_url("http://localhost:8000/api/health")
    assert not brand_contacts._is_safe_public_url("http://169.254.169.254/latest/meta-data")
    assert not brand_contacts._is_safe_public_url("http://10.0.0.1/contact")
    assert not brand_contacts._is_safe_public_url("file:///etc/passwd")
    assert not brand_contacts._is_safe_public_url("https://user:pass@goodles.com/contact")


def test_lookup_contact_endpoint_verified_email_and_web_form(client: TestClient) -> None:
    # 1. Verified email brand
    res_goodles = client.get("/api/brands/lookup-contact", params={"brand": "Goodles"})
    assert res_goodles.status_code == 200
    body = res_goodles.json()
    assert body["source"] == "verified_directory"
    assert body["verified"] is True
    assert body["contact_type"] == "email"
    assert body["email"] == "help@goodles.com"
    assert body["contact_url"] == "https://www.goodles.com/contact/"

    # 2. Verified web-form brand (sub-brand resolving to parent)
    res_kraft = client.get("/api/brands/lookup-contact", params={"brand": "Philadelphia"})
    assert res_kraft.status_code == 200
    kbody = res_kraft.json()
    assert kbody["source"] == "verified_directory"
    assert kbody["verified"] is True
    assert kbody["brand"] == "Kraft Heinz"
    assert kbody["contact_type"] == "web_form"
    assert kbody["email"] is None
    assert kbody["contact_url"] == "https://contactus.kraftheinz.com/en-us"


def test_lookup_contact_endpoint_unknown_brand_web_discovery(
    client: TestClient, monkeypatch
) -> None:
    def fake_web_lookup(brand: str):
        html = """
        <html><body>
          <a href="mailto:noreply@acmesnacks.com">No Reply</a>
          <a href="mailto:hello@example.com">Placeholder</a>
          <a href="mailto:care@acmesnacks.com">Customer Care</a>
          <a href="mailto:info@thirdparty.com">Vendor</a>
          <p>Call us at 1-800-555-0199</p>
        </body></html>
        """
        email, phone = brand_contacts._extract_email_and_phone_from_html(
            html, "https://www.acmesnacks.com/contact-us"
        )
        return "https://www.acmesnacks.com/contact-us", email, phone

    monkeypatch.setattr(brand_contacts, "_web_lookup_brand_contact", fake_web_lookup)

    res = client.get("/api/brands/lookup-contact", params={"brand": "Acme Snacks"})
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "web_lookup"
    assert body["verified"] is False
    assert body["contact_type"] == "email"
    assert body["email"] == "care@acmesnacks.com"
    assert body["contact_url"] == "https://www.acmesnacks.com/contact-us"
    assert body["phone"] == "1-800-555-0199"


def test_lookup_contact_endpoint_not_found_and_validation(client: TestClient) -> None:
    res = client.get(
        "/api/brands/lookup-contact",
        params={"brand": "CompletelyUnknownLocalBakeryXYZ", "allow_web": "false"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "not_found"
    assert body["verified"] is False
    assert body["contact_type"] == "unknown"
    assert body["email"] is None
    assert body["contact_url"] is None
    assert "google.com/search" in body["search_url"]

    bad = client.get("/api/brands/lookup-contact", params={"brand": "   "})
    assert bad.status_code == 422
