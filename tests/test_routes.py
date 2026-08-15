"""End-to-end test of routes.py against a real FastAPI TestClient, plus a
network-mocked proxy test (no live HTTP in CI). Mirrors the pattern used
by the sibling ``tekflox/aw-app-whiteboard`` migration.

Run: .venv/aw/bin/python -m pytest tests/test_routes.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_browser_app import routes as routes_mod  # noqa: E402


@pytest.fixture
def client():
    app = routes_mod.build_routes("https://example.com")
    return TestClient(app)


def test_view_shell_renders(client):
    resp = client.get("/view")
    assert resp.status_code == 200
    assert "https://example.com" in resp.text
    assert "proxy?url=" in resp.text


def test_proxy_rejects_non_http_url(client):
    resp = client.get("/proxy", params={"url": "javascript:alert(1)"})
    assert resp.status_code == 400


def test_proxy_strips_blocking_headers(client, monkeypatch):
    async def fake_get(self, url, headers=None):
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "x-frame-options": "SAMEORIGIN",
                "content-security-policy": "frame-ancestors 'self'",
            },
            content=b"<html><head></head><body>hi</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = client.get("/proxy", params={"url": "https://blocked.example/"})
    assert resp.status_code == 200
    assert "x-frame-options" not in {k.lower() for k in resp.headers}
    assert "content-security-policy" not in {k.lower() for k in resp.headers}
    assert "<base href=" in resp.text


def test_browser_screenshot_returns_png(client, monkeypatch):
    from mini_browser_app.cdp import client as browser_client

    async def fake_screenshot(fmt="png"):
        return b"\x89PNG\r\n\x1a\n-fake-"

    monkeypatch.setattr(browser_client, "screenshot", fake_screenshot)

    resp = client.get("/browser/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


def test_browser_navigate_calls_cdp_client(client, monkeypatch):
    from mini_browser_app.cdp import client as browser_client

    seen = {}

    async def fake_navigate(url):
        seen["url"] = url

    monkeypatch.setattr(browser_client, "navigate", fake_navigate)

    resp = client.post("/browser/navigate", json={"url": "https://www.google.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "url": "https://www.google.com"}
    assert seen["url"] == "https://www.google.com"


def test_browser_current_returns_title_and_url(client, monkeypatch):
    from mini_browser_app.cdp import client as browser_client

    async def fake_current():
        return {"title": "Google", "url": "https://www.google.com/"}

    monkeypatch.setattr(browser_client, "current", fake_current)

    resp = client.get("/browser/current")
    assert resp.status_code == 200
    assert resp.json() == {"title": "Google", "url": "https://www.google.com/"}


def test_browser_screenshot_cdp_failure_returns_502(client, monkeypatch):
    from mini_browser_app.cdp import client as browser_client

    async def fake_screenshot(fmt="png"):
        raise RuntimeError("aw-app-browser not reachable")

    monkeypatch.setattr(browser_client, "screenshot", fake_screenshot)

    resp = client.get("/browser/screenshot")
    assert resp.status_code == 502
    assert resp.json()["error"] == "browser"


def test_window_spec_endpoints_are_registered():
    """windows/main.json's iframe widget must reference a real route on
    this app's own FastAPI sub-app — a stale path here would 404 silently
    inside the SPA's window with no test ever catching it."""
    app = routes_mod.build_routes("https://example.com")
    registered = {(next(iter(r.methods - {"HEAD"})), r.path) for r in app.routes if hasattr(r, "methods")}

    spec = json.loads((ROOT / "windows" / "main.json").read_text())
    for region in spec["regions"]:
        for widget in region["widgets"]:
            if widget["type"] == "iframe":
                path = widget["src"].removeprefix("/api/apps/mini-browser")
                assert ("GET", path) in registered, f"iframe src {path!r} has no matching route"
