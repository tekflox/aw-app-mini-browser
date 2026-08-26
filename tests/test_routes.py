"""End-to-end test of routes.py against a real FastAPI TestClient, plus a
network-mocked proxy test (no live HTTP in CI). Mirrors the pattern used
by the sibling ``tekflox/aw-app-whiteboard`` migration.

Run: .venv/aw/bin/python -m pytest tests/test_routes.py
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_TOKEN = "test-token"

# view() and bare_server.py's data endpoint both do
# `from src.api.identity import ...` at call time — real workspace core,
# not installed in this repo's own isolated test venv (CI has no
# /opt/aw-workspace on its path, and never should: this repo has to stay
# independently testable). Stub the module in sys.modules BEFORE anything
# imports it, rather than monkeypatching an attribute that doesn't exist
# here in the first place.
_fake_identity = types.ModuleType("src.api.identity")
_fake_identity.COOKIE_NAME = "aw_id_jwt"
_fake_identity.decode_identity_jwt = lambda token: (
    {"sub": "test-user"} if token == FAKE_TOKEN else None
)
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.api", types.ModuleType("src.api"))
sys.modules["src.api.identity"] = _fake_identity

# bare_server.py's WS tunnel route does `import websockets` lazily inside
# the function under test (same reasoning as above: CI's baseline install
# doesn't include app-specific pip_requires). Stub it when the real package
# isn't present so the WS test can monkeypatch `.connect` either way.
try:
    import websockets  # noqa: F401
except ModuleNotFoundError:
    _fake_websockets = types.ModuleType("websockets")
    _fake_websockets.connect = None
    sys.modules["websockets"] = _fake_websockets

from mini_browser_app import routes as routes_mod  # noqa: E402


@pytest.fixture
def client():
    app = routes_mod.build_routes("https://example.com")
    return TestClient(app)


def test_view_shell_renders(client):
    resp = client.get("/view", cookies={"aw_id_jwt": FAKE_TOKEN})
    assert resp.status_code == 200
    assert "https://example.com" in resp.text
    assert "uv/sw.js" in resp.text
    assert "BareMuxConnection" in resp.text
    assert 'allow="camera"' in resp.text
    assert FAKE_TOKEN in resp.text


def test_view_requires_identity(client):
    resp = client.get("/view")
    assert resp.status_code == 401

    resp = client.get("/view", cookies={"aw_id_jwt": "garbage"})
    assert resp.status_code == 401


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


def test_bare_data_rejects_unknown_token(client):
    resp = client.get("/bare/not-a-real-token/v3/", headers={"x-bare-url": "https://example.com/"})
    assert resp.status_code == 401


def test_bare_data_requires_bare_url_header(client):
    resp = client.get(f"/bare/{FAKE_TOKEN}/v3/")
    assert resp.status_code == 400
    assert resp.json()["code"] == "MISSING_BARE_HEADER"


def test_bare_data_rejects_invalid_headers_json(client):
    resp = client.get(f"/bare/{FAKE_TOKEN}/v3/", headers={"x-bare-url": "https://example.com/", "x-bare-headers": "not-json"})
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
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={"x-bare-url": "https://example.com/", "x-bare-headers": json.dumps({"Accept": "*/*"})},
    )
    assert resp.status_code == 200
    assert resp.content == b"hello from upstream"
    assert resp.headers["x-bare-status"] == "200"
    remote_headers = json.loads(resp.headers["x-bare-headers"])
    assert remote_headers["x-upstream"] == "yes"


def test_bare_data_does_not_echo_upstream_content_encoding(client, monkeypatch):
    # httpx.AsyncClient auto-decompresses the upstream body during the real
    # transport read (upstream.content ends up plain) but leaves
    # upstream.headers reporting the original content-encoding/content-length
    # — echoing those verbatim told the downstream fetch() to re-decompress
    # already-plain bytes, which hard failed real navigation (aol.com,
    # uol.com.br: both gzip). Regression test for that — genuinely gzip the
    # body so httpx.Response's own constructor-time decode (which real bytes
    # off the wire go through too) leaves upstream.content plain, exactly
    # mirroring what a real upstream fetch produces.
    import gzip as gzip_mod

    plain_body = b"<html>already decompressed by httpx</html>"

    async def fake_request(self, method, url, headers=None, content=None):
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "gzip", "content-length": "999"},
            content=gzip_mod.compress(plain_body),
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.get(
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={"x-bare-url": "https://example.com/", "x-bare-headers": "{}"},
    )
    assert resp.status_code == 200
    assert resp.content == plain_body
    assert "content-encoding" not in resp.headers
    assert resp.headers["content-length"] == str(len(resp.content))
    # x-bare-headers is a SEPARATE copy of upstream.headers that the UV
    # client uses to rebuild the page-visible Response — it told the same
    # lie independently of the direct response headers above, and the
    # client re-decompressed the already-plain body a second time,
    # rendering as garbled text. Regression test for that second copy.
    remote_headers = json.loads(resp.headers["x-bare-headers"])
    assert "content-encoding" not in remote_headers
    assert "content-length" not in remote_headers


def test_bare_data_caps_accept_encoding_to_what_httpx_can_decode(client, monkeypatch):
    # The browser's own fetch() advertises br/zstd in its Accept-Encoding,
    # and that header gets forwarded straight through to the upstream — but
    # httpx only auto-decompresses gzip/deflate (no brotli/zstandard package
    # installed here). An upstream that picks br for its response leaves
    # upstream.content still compressed; since we strip content-encoding
    # from what we send back, the client has no signal to decode it either
    # — reproduced live on cloudflare.com after the gzip-only fix above,
    # rendering as garbled binary-as-text. Regression test: whatever the
    # browser sends, upstream only ever gets asked for gzip/deflate.
    captured = {}

    async def fake_request(self, method, url, headers=None, content=None):
        captured["accept-encoding"] = {k.lower(): v for k, v in headers.items()}.get("accept-encoding")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>ok</html>",
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    resp = client.get(
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={
            "x-bare-url": "https://example.com/",
            "x-bare-headers": "{}",
            "accept-encoding": "gzip, deflate, br, zstd",
        },
    )
    assert resp.status_code == 200
    assert captured["accept-encoding"] == "gzip, deflate"


def test_bare_data_forwards_identity_only_to_this_workspace(monkeypatch):
    captured = []

    async def fake_request(self, method, url, headers=None, content=None):
        captured.append({k.lower(): v for k, v in (headers or {}).items()})
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    app = routes_mod.build_routes("https://example.com")
    scoped = TestClient(app, base_url="https://api.aw.workspace.aw.tekflox.com")
    common = {"x-bare-headers": "{}"}

    scoped.get(
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={**common, "x-bare-url": "https://aw-app-portrait.app.aw.workspace.aw.tekflox.com/"},
    )
    scoped.get(
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={**common, "x-bare-url": "https://example.com/"},
    )
    scoped.get(
        f"/bare/{FAKE_TOKEN}/v3/",
        headers={**common, "host": "internal:9030", "origin": "https://api.aw.workspace.aw.tekflox.com", "x-bare-url": "https://aw-app-portrait.app.aw.workspace.aw.tekflox.com/"},
    )

    assert captured[0]["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert "authorization" not in captured[1]
    assert captured[2]["authorization"] == f"Bearer {FAKE_TOKEN}"


def test_bare_ws_rejects_unknown_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/bare/not-a-real-token/v3/"):
            pass


def test_bare_ws_rejects_non_connect_first_message(client):
    with client.websocket_connect(f"/bare/{FAKE_TOKEN}/v3/") as ws:
        ws.send_text(json.dumps({"type": "not-connect"}))
        with pytest.raises(Exception):
            ws.receive_text()


class _FakeRemoteWS:
    def __init__(self, to_client):
        self.subprotocol = None
        self.sent = []
        self.closed = False
        self._to_client = list(to_client)

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._to_client:
            return self._to_client.pop(0)
        raise StopAsyncIteration


def test_bare_ws_tunnels_messages_bidirectionally(client, monkeypatch):
    import websockets

    fake = _FakeRemoteWS(["hello-from-remote"])

    async def fake_connect(url, subprotocols=None, additional_headers=None, open_timeout=None):
        assert url == "wss://example.com/socket"
        return fake

    monkeypatch.setattr(websockets, "connect", fake_connect)

    with client.websocket_connect(f"/bare/{FAKE_TOKEN}/v3/") as ws:
        ws.send_text(json.dumps({
            "type": "connect",
            "remote": "wss://example.com/socket",
            "protocols": [],
            "headers": {},
        }))
        open_msg = json.loads(ws.receive_text())
        assert open_msg["type"] == "open"

        assert ws.receive_text() == "hello-from-remote"

        ws.send_text("ping-from-client")

    assert fake.sent == ["ping-from-client"]
    assert fake.closed


def _fake_devctl_eval(devctl_response, monkeypatch):
    async def fake_post(self, url, json=None, timeout=None):
        assert url.endswith("/api/apps/devctl/eval")
        return httpx.Response(200, json=devctl_response, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def test_pilot_status_success(client, monkeypatch):
    _fake_devctl_eval({
        "ok": True,
        "result": {"type": "mb-pilot-result", "id": "x", "result": {"url": "https://example.com", "status": "Ready", "engineReady": True}},
    }, monkeypatch)

    resp = client.get("/pilot/status")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": {"url": "https://example.com", "status": "Ready", "engineReady": True}}


def test_pilot_navigate_requires_url(client):
    resp = client.post("/pilot/navigate", json={})
    assert resp.status_code == 400


def test_pilot_no_window_open_returns_502(client, monkeypatch):
    _fake_devctl_eval({
        "ok": True,
        "result": {"error": "mini-browser window not found — ask the user to open it"},
    }, monkeypatch)

    resp = client.post("/pilot/navigate", json={"url": "https://example.com"})
    assert resp.status_code == 502
    assert "not found" in resp.json()["error"]


def test_pilot_no_connected_tab_returns_502(client, monkeypatch):
    _fake_devctl_eval({"ok": False, "error": "no connected tab"}, monkeypatch)

    resp = client.get("/pilot/status")
    assert resp.status_code == 502
    assert resp.json()["error"] == "no connected tab"


def test_pilot_click_requires_coords(client):
    resp = client.post("/pilot/click", json={"x": 10})
    assert resp.status_code == 400


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


# ---------------------------------------------------------------------------
# borrowed browser cookies (see mini_browser_app/cookies.py)
# ---------------------------------------------------------------------------

def _bare_client_with_cookies(config):
    """A client whose bare server is wired to a bridge built from ``config``,
    with the proxy's /cookies-for stubbed to always hand back one cookie."""
    app = routes_mod.build_routes("https://example.com", config)
    return TestClient(app)


def _capture_upstream(monkeypatch):
    seen = {}

    async def fake_request(self, method, url, headers=None, content=None):
        seen["headers"] = dict(headers or {})
        return httpx.Response(200, content=b"ok", request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    return seen


def _stub_proxy_reply(monkeypatch, cookies):
    class _Resp:
        status_code = 200

        def json(self):
            return {"cookies": cookies}

    async def fake_get(self, url, params=None, **_kw):
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


def test_bare_data_attaches_borrowed_cookies_when_enabled(monkeypatch):
    seen = _capture_upstream(monkeypatch)
    _stub_proxy_reply(monkeypatch, [{"name": "SID", "value": "borrowed"}])
    client = _bare_client_with_cookies(
        {"share_browser_cookies": True, "cookie_share_hosts": ["example.com"]})

    client.get(f"/bare/{FAKE_TOKEN}/v3/",
               headers={"x-bare-url": "https://example.com/", "x-bare-headers": "{}"})

    assert seen["headers"]["cookie"] == "SID=borrowed"


def test_bare_data_sends_no_cookies_when_the_feature_is_off(monkeypatch):
    seen = _capture_upstream(monkeypatch)
    _stub_proxy_reply(monkeypatch, [{"name": "SID", "value": "borrowed"}])
    client = _bare_client_with_cookies({})   # default config = feature off

    client.get(f"/bare/{FAKE_TOKEN}/v3/",
               headers={"x-bare-url": "https://example.com/", "x-bare-headers": "{}"})

    assert "cookie" not in {k.lower() for k in seen["headers"]}


def test_bare_data_keeps_ultraviolets_own_cookie_on_conflict(monkeypatch):
    seen = _capture_upstream(monkeypatch)
    _stub_proxy_reply(monkeypatch, [{"name": "SID", "value": "borrowed"}])
    client = _bare_client_with_cookies(
        {"share_browser_cookies": True, "cookie_share_hosts": ["example.com"]})

    client.get(f"/bare/{FAKE_TOKEN}/v3/",
               headers={"x-bare-url": "https://example.com/",
                        "x-bare-headers": json.dumps({"Cookie": "SID=from-uv"})})

    assert seen["headers"]["cookie"] == "SID=from-uv"


def test_bare_data_skips_hosts_outside_the_allowlist(monkeypatch):
    seen = _capture_upstream(monkeypatch)
    _stub_proxy_reply(monkeypatch, [{"name": "SID", "value": "borrowed"}])
    client = _bare_client_with_cookies(
        {"share_browser_cookies": True, "cookie_share_hosts": ["google.com"]})

    client.get(f"/bare/{FAKE_TOKEN}/v3/",
               headers={"x-bare-url": "https://example.com/", "x-bare-headers": "{}"})

    assert "cookie" not in {k.lower() for k in seen["headers"]}
