"""DOM shape assertions for the annotation UI. Pure string checks."""
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "html_mcp" / "ui"


def test_index_has_anno_toggle_button():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-toggle"' in html


def test_index_has_token_dialog():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="anno-token-dialog"' in html
    assert 'id="anno-token-input"' in html
    assert 'id="anno-token-submit"' in html


def test_index_has_anno_sidebar():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-sidebar"' in html
    assert 'id="anno-list"' in html


def test_css_has_anno_mode_styles():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "#anno-toggle" in css
    assert "#anno-sidebar" in css
    assert "dialog" in css.lower() or "#anno-token-dialog" in css