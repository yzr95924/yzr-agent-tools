"""Tests for html_mcp.storage.annotations — ULID, author hash, quote normalize."""
from html_mcp.storage.annotations import load, ulid_new, author_of_token, normalize_quote


def test_load_non_utf8_meta_returns_empty_doc(tmp_path):
    (tmp_path / "example.meta").write_bytes(b"\xff\xfe\x80")

    assert load(tmp_path, "example") == {"version": 1, "annotations": []}


def test_ulid_new_is_26_chars():
    assert len(ulid_new()) == 26


def test_ulid_new_is_uppercase_alphanumeric():
    import re
    assert re.match(r"^[0-9A-Z]{26}$", ulid_new())


def test_ulid_new_is_unique():
    seen = {ulid_new() for _ in range(1000)}
    assert len(seen) == 1000


def test_author_of_token_is_tk_prefix():
    assert author_of_token("any").startswith("tk_")


def test_author_of_token_is_deterministic():
    assert author_of_token("hello") == author_of_token("hello")


def test_author_of_token_is_irreversible_8_hex():
    a = author_of_token("hello")
    suffix = a[len("tk_"):]
    assert len(suffix) == 8
    assert all(c in "0123456789abcdef" for c in suffix)


def test_author_differs_per_token():
    assert author_of_token("a") != author_of_token("b")


def test_normalize_quote_collapses_whitespace():
    assert normalize_quote("  hello\n\n world  ") == "hello world"


def test_normalize_quote_preserves_cn_punct():
    # Chinese full-width punctuation must NOT be touched.
    assert normalize_quote("你好，世界") == "你好，世界"