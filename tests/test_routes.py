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
    assert "uv/sw.js" in resp.text
    assert "BareMuxConnection" in resp.text


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


def test_view_screenshot_requires_a_url(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "_last_url", None)
    resp = client.get("/view/screenshot")
    assert resp.status_code == 400


def test_view_screenshot_defaults_to_last_navigated_url(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "_last_url", "https://example.com/from-proxy")
    seen = {}

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        seen["url"], seen["json"] = url, json
        return httpx.Response(200, headers={"content-type": "image/png"},
                               content=b"\x89PNG\r\n\x1a\n-fake-",
                               request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    resp = client.get("/view/screenshot")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\x89PNG")
    assert seen["json"] == {"url": "https://example.com/from-proxy"}
    assert seen["url"].endswith("/api/apps/devctl/render/screenshot")


def test_view_screenshot_url_param_overrides_last_navigated(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "_last_url", "https://example.com/old")
    seen = {}

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        seen["json"] = json
        return httpx.Response(200, headers={"content-type": "image/png"},
                               content=b"\x89PNG-fake-", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    resp = client.get("/view/screenshot", params={"url": "https://example.com/new"})
    assert resp.status_code == 200
    assert seen["json"] == {"url": "https://example.com/new"}


def test_view_screenshot_devctl_failure_returns_502(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "_last_url", "https://example.com/x")

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(502, text="render failed", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    resp = client.get("/view/screenshot")
    assert resp.status_code == 502
    assert resp.json()["error"] == "devctl"


def test_track_nav_records_last_url(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "_last_url", None)
    resp = client.get("/track-nav", params={"url": "https://example.com/via-uv"})
    assert resp.status_code == 200
    assert routes_mod._last_url == "https://example.com/via-uv"


def test_proxy_records_last_url(client, monkeypatch):
    async def fake_get(self, url, headers=None):
        return httpx.Response(200, headers={"content-type": "text/plain"},
                               content=b"hi", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(routes_mod, "_last_url", None)

    client.get("/proxy", params={"url": "https://example.com/tracked"})
    assert routes_mod._last_url == "https://example.com/tracked"


def test_uv_static_files_served(client):
    resp = client.get("/uv/uv.config.js")
    assert resp.status_code == 200
    assert b"prefix" in resp.content

    resp = client.get("/uv/sw.js")
    assert resp.status_code == 200
    assert b"uv.bundle.js" in resp.content


def test_bare_info_endpoint(client):
    resp = client.get("/bare/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["versions"] == ["v3"]
    assert body["language"] == "Python"


def test_bare_data_requires_bare_url_header(client):
    resp = client.get("/bare/v3/")
    assert resp.status_code == 400
    assert resp.json()["code"] == "MISSING_BARE_HEADER"


def test_bare_data_rejects_invalid_headers_json(client):
    resp = client.get("/bare/v3/", headers={"x-bare-url": "https://example.com/", "x-bare-headers": "not-json"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BARE_HEADER"


def test_bare_data_proxies_and_wraps_status(client, monkeypatch):
    async def fake_request(self, method, url, headers=None, content=None):
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "x-upstream": "yes"},
            content=b"hello from upstream",
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.get(
        "/bare/v3/",
        headers={"x-bare-url": "https://example.com/", "x-bare-headers": json.dumps({"Accept": "*/*"})},
    )
    assert resp.status_code == 200
    assert resp.content == b"hello from upstream"
    assert resp.headers["x-bare-status"] == "200"
    remote_headers = json.loads(resp.headers["x-bare-headers"])
    assert remote_headers["x-upstream"] == "yes"


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
