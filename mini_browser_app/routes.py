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

Intentionally simple (regex-based HTML patch, not a full URL-rewriting
proxy like Ultraviolet/Rammerhead) — good for static/simple sites, not
guaranteed for JS-heavy SPAs with anti-iframe checks.
"""

from __future__ import annotations

import re

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from .viewer import VIEWER_SHELL

_BLOCKED_RESPONSE_HEADERS = {
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
    "content-length",  # body length changes once we inject <base>
    "content-encoding",  # httpx already decodes for us
    "transfer-encoding",
}


def build_routes(home_url: str) -> FastAPI:
    api = FastAPI()
    client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)

    @api.get("/view")
    async def view():
        return HTMLResponse(content=VIEWER_SHELL.replace("__HOME_URL__", home_url))

    @api.get("/proxy")
    async def proxy(url: str = Query(..., description="Absolute http(s) URL to fetch")):
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise HTTPException(400, "url must start with http:// or https://")

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

    return api
