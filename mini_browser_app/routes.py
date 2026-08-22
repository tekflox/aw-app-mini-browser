"""Mini Browser routes — mounted at ``/api/apps/mini-browser`` by the
runtime (``routes:register`` contribution point).

* ``GET /view`` — the browser UI shell (URL bar, back/forward/reload/home,
  an iframe). Ported from the standalone prototype validated in
  ``agentic-workspace/src/custom_apps/mini-browser`` — same proxy design,
  now namespaced under this app's own route prefix.
* ``GET /proxy`` — fetches a target URL server-side and strips the
  response headers (``X-Frame-Options``, CSP ``frame-ancestors``) that
  would otherwise stop the browser's own iframe from displaying it. Only
  the top-level document's blocking headers need stripping — sub-resources
  (images, CSS, XHR/fetch) aren't being framed, so they're left to load
  directly from the origin via an injected ``<base>`` tag.
* ``/browser/*`` — piloted-browser routes ported from ``tekflox/aw-app-devctl``
  (``devctl_app/routes.py``), driving the shared ``aw-app-browser`` CDP
  container. These are the HTTP twin of ``mcp_server/mini_browser_browser.py``'s
  MCP tools — an agent calls the MCP tool to act, and (since a stdio MCP
  server runs inside the mcp-gateway container, not this one) fetches bytes
  like a screenshot back through this Tier-1 HTTP route instead, which shares
  the filesystem the agent runner sees. See the workspace KB memory
  "how-an-agent-sends-a-screenshot".
* ``GET /view/screenshot`` — screenshots whatever URL this window's own
  iframe last loaded (tracked in ``_last_url`` below, set by
  ``/track-nav`` — pinged fire-and-forget from ``/view``'s own JS on every
  navigation, since navigation itself now goes through the UV service
  worker, not through this process), or an explicit ``?url=`` override.
  Delegates the actual rendering to the
  ``devctl`` app's ``POST /render/screenshot`` (a throwaway in-process
  Playwright chromium, no side container) — this app declares that as a
  hard dependency, see ``aw-app.json``'s ``dependencies``.
* ``GET /track-nav`` — fire-and-forget ping from ``/view``'s own JS on
  every navigation, so ``_last_url`` keeps tracking reality now that
  navigation itself goes through the UV service worker instead of this
  process.
* ``/uv/*`` — static files for a vendored Ultraviolet (see
  ``static/uv/``) — the real rewriting proxy ``/view``'s iframe now
  navigates through, intercepted client-side by a service worker
  (``uv/sw.js``). ``/proxy`` above is UNUSED by ``/view`` as of this
  version; kept only for anything else that might still call it directly.
* ``/bare/*`` (``bare_server.py``) — this app's own TompHTTP Bare Server
  v3 backend, the thing the vendored client actually calls out to on
  every proxied request. Written from the open spec, not vendored — see
  ``bare_server.py``'s docstring for why (Wisp's only Python server is
  AGPL and needs its own process; this doesn't).

Ultraviolet + bare-mux are AGPL-3.0 / MIT respectively (see
``static/uv/licenses/``) — AGPL's network-copyleft clause is about
*offering* the software to third-party users over a network; this
instance is operated and used by its own owner, not offered to others,
but it's a real licensing fact worth knowing, not just a technical one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .bare_server import build_bare_routes
from .cdp import client as browser_client
from .viewer import VIEWER_SHELL

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_BLOCKED_RESPONSE_HEADERS = {
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
    "content-length",  # body length changes once we inject <base>
    "content-encoding",  # httpx already decodes for us
    "transfer-encoding",
}

# The last URL a human navigated to via this window's own /proxy (i.e. what
# the iframe is actually showing right now) — one workspace, one Mini
# Browser window, so a single module-level value is enough; no per-session
# tracking exists anywhere else in this app either.
_last_url: str | None = None


def build_routes(home_url: str) -> FastAPI:
    api = FastAPI()
    client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)
    devctl_base = f"http://127.0.0.1:{os.environ.get('AW_PORT', '9030')}/api/apps/devctl"

    api.mount("/uv", StaticFiles(directory=str(_STATIC_DIR / "uv")), name="uv-static")
    api.mount("/bare", build_bare_routes())

    @api.get("/view")
    async def view():
        return HTMLResponse(content=VIEWER_SHELL.replace("__HOME_URL__", home_url))

    @api.get("/track-nav")
    async def track_nav(url: str = Query(..., description="URL the UV-powered /view just navigated to")):
        global _last_url
        _last_url = url
        return {"ok": True}

    @api.get("/proxy")
    async def proxy(url: str = Query(..., description="Absolute http(s) URL to fetch")):
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise HTTPException(400, "url must start with http:// or https://")

        global _last_url
        _last_url = url

        try:
            upstream = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; MiniBrowser/1.0; +internal-tool)"
                    )
                },
            )
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Fetch failed: {exc}") from exc

        content_type = upstream.headers.get("content-type", "text/plain")
        body = upstream.content

        if "text/html" in content_type:
            html = upstream.text
            base_tag = f'<base href="{upstream.url}">'
            if re.search(r"<head[^>]*>", html, re.IGNORECASE):
                html = re.sub(
                    r"(<head[^>]*>)", r"\1" + base_tag, html, count=1, flags=re.IGNORECASE
                )
            else:
                html = base_tag + html
            html = re.sub(
                r'<meta[^>]+http-equiv=["\']content-security-policy["\'][^>]*>',
                "",
                html,
                flags=re.IGNORECASE,
            )
            body = html.encode("utf-8")

        headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _BLOCKED_RESPONSE_HEADERS
        }

        return Response(content=body, media_type=content_type, headers=headers)

    async def _guard(fn):
        try:
            return await fn()
        except Exception as exc:  # surface CDP/browser errors as 502, not 500
            return JSONResponse(status_code=502, content={"error": "browser", "detail": str(exc)})

    @api.get("/browser/screenshot")
    async def browser_screenshot():
        try:
            png = await browser_client.screenshot()
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": "browser", "detail": str(exc)})
        return Response(content=png, media_type="image/png")

    @api.get("/browser/current")
    async def browser_current():
        return await _guard(browser_client.current)

    @api.post("/browser/navigate")
    async def browser_navigate(body: dict = Body(...)):
        async def go():
            await browser_client.navigate(body["url"])
            return {"ok": True, "url": body["url"]}
        return await _guard(go)

    @api.get("/view/screenshot")
    async def view_screenshot(url: str | None = Query(None, description="Defaults to the last URL loaded in this window")):
        target = url or _last_url
        if not target:
            raise HTTPException(400, "nothing has been navigated to yet — pass ?url= explicitly")
        api_key = os.environ.get("AW_WORKSPACE_API_KEY")
        headers = {"X-Api-Key": api_key} if api_key else {}
        try:
            resp = await client.post(
                f"{devctl_base}/render/screenshot",
                json={"url": target},
                headers=headers,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            return JSONResponse(status_code=502, content={"error": "devctl", "detail": str(exc)})
        if resp.status_code != 200:
            return JSONResponse(status_code=502, content={"error": "devctl", "detail": resp.text})
        return Response(content=resp.content, media_type="image/png")

    return api
