"""A minimal TompHTTP Bare Server v3 backend — the piece the vendored
Ultraviolet client (via the `bare-as-module3` transport, see
``static/uv/bare-module3/``) actually talks to for every proxied request.

Spec: https://github.com/tomphttp/specifications/blob/master/BareServerV3.md
Implements the subset this app's traffic needs: the info endpoint and the
plain HTTP data endpoint. No WebSocket tunnel yet (see the aw-mini-browser
skill's pendências list) — a proxied page whose JS opens a raw WebSocket
will fail; regular HTTP navigation/fetch/XHR works.

Written from scratch against the open spec (not vendored) specifically to
avoid pulling in Wisp/wisp-server-python, whose only Python implementation
is AGPL-3.0 and runs as its own process — neither fits "no new
process/container, keep it simple".

**Auth, two independent layers, easy to conflate:**

1. **Workspace edge tunnel** (`aw-backend`'s `workspace_tunnel_proxy.py`,
   a DIFFERENT repo): requires some credential-shaped header/cookie to be
   merely PRESENT before forwarding a request at all — never checks
   validity, that's deferred one hop in. `bare-as-module3` hardcodes
   `credentials: "omit"` (confirmed live: zero cookie ever reaches this
   backend), so `static/uv/bare-module3/index.mjs` is patched (see
   `VENDORED.md`) to add a fixed, non-secret placeholder `X-Api-Key`
   header — purely to satisfy that presence check. **This backend ignores
   that header entirely.**
2. **This app's own auth** (what actually matters): the workspace's
   normal cookie-based ``IdentityGuard`` can never pass here either (same
   `credentials:"omit"` problem, no cookie ever arrives), which forces
   this whole app's ``auth_required`` to ``false`` in its settings
   (framework "app decides" mode — see ``aw-app.json``'s
   ``config_schema``). Left unguarded that would make ``/bare/*`` a
   genuinely open relay (SSRF/abuse risk: anyone who finds the URL could
   use this workspace to make arbitrary outbound HTTP requests) — so the
   data endpoint below re-verifies the SAME real identity JWT the rest of
   the workspace already uses (``decode_identity_jwt`` straight from
   ``src.api.identity``, no new verification logic), carried as a URL
   path segment — the one channel this app DOES control (the base server
   URL passed to `bare-as-module3`'s constructor). See ``routes.py``'s
   ``/view`` for where that token gets embedded.
"""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

_BASE_PASS_HEADERS = {"content-encoding", "content-length", "last-modified"}
_BASE_FORWARD_HEADERS = {"accept-encoding", "accept-language"}
_CACHE_EXTRA = {"if-modified-since", "if-none-match", "cache-control"}
_CACHE_EXTRA_STATUS = {304}

# Hop-by-hop / connection-management headers we must never forward verbatim
# in either direction — httpx and the ASGI server each manage these.
_STRIP_REQUEST_HEADERS = {
    "host", "connection", "content-length", "x-bare-url", "x-bare-headers",
    "x-bare-forward-headers", "x-bare-pass-headers", "x-bare-pass-status",
}


def build_bare_routes() -> FastAPI:
    api = FastAPI()
    client = httpx.AsyncClient(follow_redirects=False, timeout=30.0)

    @api.get("/")
    async def info():
        return JSONResponse({
            "versions": ["v3"],
            "language": "Python",
            "project": {
                "name": "aw-mini-browser bare server",
                "description": "Minimal Bare Server v3 backend for this app's vendored Ultraviolet client",
                "repository": "https://github.com/tekflox/aw-app-mini-browser",
            },
        })

    @api.api_route(
        "/{token}/v3/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def data(token: str, request: Request):
        from src.api.identity import decode_identity_jwt

        if not decode_identity_jwt(token):
            raise HTTPException(401, "unauthorized")

        bare_url = request.headers.get("x-bare-url")
        if not bare_url:
            return JSONResponse(
                status_code=400,
                content={"code": "MISSING_BARE_HEADER", "message": "X-Bare-URL is required"},
            )
        try:
            bare_headers: dict = json.loads(request.headers.get("x-bare-headers") or "{}")
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"code": "INVALID_BARE_HEADER", "message": "X-Bare-Headers is not valid JSON"},
            )

        caching = "cache" in request.query_params

        forward = set(_BASE_FORWARD_HEADERS) | (_CACHE_EXTRA if caching else set())
        if client_forward := request.headers.get("x-bare-forward-headers"):
            forward |= {h.strip().lower() for h in json.loads(client_forward)}

        upstream_headers = {k: v for k, v in bare_headers.items() if k.lower() not in _STRIP_REQUEST_HEADERS}
        existing_lower = {k.lower() for k in upstream_headers}
        for name in forward:
            if name in request.headers and name not in existing_lower:
                upstream_headers[name] = request.headers[name]

        body = await request.body()

        try:
            upstream = await client.request(
                request.method,
                bare_url,
                headers=upstream_headers,
                content=body or None,
            )
        except httpx.HTTPError as exc:
            return JSONResponse(status_code=502, content={"code": "UNKNOWN_ERROR", "message": str(exc)})

        pass_headers = set(_BASE_PASS_HEADERS) | (_CACHE_EXTRA if caching else set())
        if client_pass := request.headers.get("x-bare-pass-headers"):
            pass_headers |= {h.strip().lower() for h in json.loads(client_pass)}

        pass_status = set(_CACHE_EXTRA_STATUS) if caching else set()
        if client_pass_status := request.headers.get("x-bare-pass-status"):
            pass_status |= {int(s) for s in json.loads(client_pass_status)}

        remote_headers = dict(upstream.headers)
        response_headers = {name: remote_headers[name] for name in pass_headers if name in remote_headers}
        response_headers["x-bare-status"] = str(upstream.status_code)
        response_headers["x-bare-status-text"] = upstream.reason_phrase or ""
        response_headers["x-bare-headers"] = json.dumps(remote_headers)

        status = upstream.status_code if upstream.status_code in pass_status else 200
        return Response(content=upstream.content, status_code=status, headers=response_headers)

    return api
