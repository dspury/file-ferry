"""Receipt human-readable export (plan §6.5)."""

from __future__ import annotations

from media_mate.application.policies import default_policy
from media_mate.application.receipts import build_receipt, export_html, export_markdown


def _receipt():
    return build_receipt(
        operation_id="op-xyz",
        kind="intake",
        app_version="0.2.4",
        protocol_version=1,
        policy=default_policy(),
        planned=[{"action": "copy", "from": "A001.mov", "to": "D/A001.mov"}],
        actual=[{"files": 3, "verified": True}],
        checksums=[{"algo": "xxhash64", "value": "abc123"}],
        warnings=["destination nearly full"],
        final_state="succeeded",
    )


def test_markdown_contains_key_fields() -> None:
    md = export_markdown(_receipt())
    assert "# Media-mate operation receipt (intake)" in md
    assert "op-xyz" in md
    assert "succeeded" in md
    assert "xxhash64" in md
    assert "destination nearly full" in md
    assert "Receipt hash (SHA-256)" in md


def test_html_contains_escaped_content() -> None:
    receipt = _receipt()
    html = export_html(receipt)
    assert "<!doctype html>" in html
    assert "op-xyz" in html
    assert "succeeded" in html
    # Content is escaped, so the raw markdown brackets are not present.
    assert "&lt;/pre&gt;" not in html
    assert "<pre>" in html


def test_html_escapes_special_chars() -> None:

    receipt = build_receipt(
        operation_id="op-<script>alert(1)</script>",
        kind="intake",
        app_version="0.2.4",
        protocol_version=1,
        final_state="failed",
    )
    html = export_html(receipt)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_handles_no_policy() -> None:
    receipt = build_receipt(
        operation_id="op-min", kind="project", app_version="0.2.4", protocol_version=1
    )
    md = export_markdown(receipt)
    assert "Storage policy" not in md  # policy section omitted when absent
    assert "op-min" in md
