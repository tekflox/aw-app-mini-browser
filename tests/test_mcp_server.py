"""Sanity tests for the mini-browser-browser MCP tool wrapper — checks the
tool surface is what agents expect (names, and that each tool actually
drives ``mini_browser_app.cdp.client`` rather than some other browser).

Run: .../aw-app-test-venv/bin/python -m pytest tests/test_mcp_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_server import mini_browser_browser as mb  # noqa: E402


@pytest.mark.asyncio
async def test_tool_names_match_devctl_parity_plus_view_screenshot():
    # One deliberate departure from devctl's tool set: browser_screenshot_view
    # targets this window's own /view (via devctl's side-container-free
    # renderer), not the CDP-piloted aw-app-browser the rest of these drive.
    tools = await mb.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "browser_screenshot",
        "browser_current",
        "browser_navigate",
        "browser_eval",
        "browser_inject",
        "browser_click",
        "browser_type",
        "browser_key",
        "browser_scroll",
        "browser_screenshot_view",
    }


@pytest.mark.asyncio
async def test_browser_navigate_drives_shared_cdp_client(monkeypatch):
    seen = {}

    async def fake_navigate(url):
        seen["url"] = url

    monkeypatch.setattr(mb.client, "navigate", fake_navigate)

    result = await mb.browser_navigate("https://www.google.com")
    assert result == {"ok": True, "url": "https://www.google.com"}
    assert seen["url"] == "https://www.google.com"


@pytest.mark.asyncio
async def test_browser_screenshot_writes_png_under_shot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_SHOT_DIR", str(tmp_path))

    async def fake_screenshot(fmt="png"):
        return b"\x89PNG\r\n\x1a\n-fake-"

    monkeypatch.setattr(mb.client, "screenshot", fake_screenshot)

    path = await mb.browser_screenshot()
    assert path.startswith(str(tmp_path))
    assert Path(path).read_bytes().startswith(b"\x89PNG")
