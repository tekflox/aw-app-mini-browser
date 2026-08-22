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
"""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI, Request
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
        "/v3/",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    )
    async def data(request: Request):
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
