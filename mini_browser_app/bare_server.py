"""A minimal TompHTTP Bare Server v3 backend — the piece the vendored
Ultraviolet client (via the `bare-as-module3` transport, see
``static/uv/bare-module3/``) actually talks to for every proxied request.

Spec: https://github.com/tomphttp/specifications/blob/master/BareServerV3.md
Implements the subset this app's traffic needs: the info endpoint, the
plain HTTP data endpoint, and a WebSocket tunnel (same `/{token}/v3/` path —
Starlette dispatches HTTP and WS scopes to their own handlers, so the two
coexist) so a proxied page's raw `new WebSocket(...)` calls work too.

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

import asyncio
import json
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .cookies import merge_cookie_header

# Deliberately excludes content-encoding/content-length: httpx.AsyncClient
# transparently decompresses the upstream body (upstream.content is already
# plain bytes) but leaves upstream.headers untouched, so echoing those two
# verbatim told the client "this body is still gzip/br" when it wasn't —
# the client's own fetch() then tried to re-decompress plain bytes and
# hard-failed the whole request (surfaced live as aol.com/uol.com.br
# throwing "TypeError: Failed to fetch" while google.com, served
# uncompressed, worked fine). Leaving content-length unset lets Starlette
# compute the correct one from the actual (decoded) body.
_BASE_PASS_HEADERS = {"last-modified"}
_BASE_FORWARD_HEADERS = {"accept-encoding", "accept-language"}
_CACHE_EXTRA = {"if-modified-since", "if-none-match", "cache-control"}
_CACHE_EXTRA_STATUS = {304}

# Hop-by-hop / connection-management headers we must never forward verbatim
# in either direction — httpx and the ASGI server each manage these.
_STRIP_REQUEST_HEADERS = {
    "host", "connection", "content-length", "x-bare-url", "x-bare-headers",
    "x-bare-forward-headers", "x-bare-pass-headers", "x-bare-pass-status",
}


def _same_workspace_target(request_host: str, target_url: str) -> bool:
    """Return true only for HTTPS hosts under this exact workspace root."""
    request_name = (request_host or "").split(":", 1)[0].lower().rstrip(".")
    parts = request_name.split(".")
    try:
        marker = parts.index("workspace")
    except ValueError:
        return False
    if marker < 1:
        return False
    workspace_root = ".".join(parts[marker - 1:])
    target = urlparse(target_url)
    target_name = (target.hostname or "").lower().rstrip(".")
    return target.scheme == "https" and (target_name == workspace_root or target_name.endswith("." + workspace_root))


def build_bare_routes(cookie_bridge=None) -> FastAPI:
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

        # The browser's own fetch() advertises br/zstd, and that gets
        # forwarded straight through above — but httpx only auto-decompresses
        # gzip/deflate (no brotli/zstandard package installed). An upstream
        # that picks br/zstd leaves upstream.content still compressed, and
        # since we strip content-encoding from the response (see below), the
        # client has no idea it needs to decode it — renders as garbled
        # binary-as-text. Cap what we advertise so upstream can only pick a
        # format we can actually undo.
        for key in [k for k in upstream_headers if k.lower() == "accept-encoding"]:
            del upstream_headers[key]
        upstream_headers["accept-encoding"] = "gzip, deflate"

        # A proxied workspace app cannot see the browser's aw_id_jwt cookie:
        # Ultraviolet intentionally owns an isolated cookie jar. The same JWT
        # already authenticated this Bare request, so forward it as a Bearer
        # token only to HTTPS hosts inside this exact workspace. Never expose
        # it to arbitrary pages opened in Mini Browser.
        if _same_workspace_target(request.headers.get("host", ""), bare_url):
            for key in [k for k in upstream_headers if k.lower() == "authorization"]:
                del upstream_headers[key]
            upstream_headers["authorization"] = f"Bearer {token}"

        # Borrow aw-app-browser's logged-in sessions, if this app is
        # configured to (off by default). Server-side on purpose: these
        # values never reach the proxied page's JS, so an HttpOnly cookie
        # stays HttpOnly. See cookies.py for the full why.
        if cookie_bridge is not None:
            parsed = urlparse(bare_url)
            borrowed = await cookie_bridge.cookies_for(bare_url, parsed.hostname or "")
            if borrowed:
                existing_key = next(
                    (k for k in upstream_headers if k.lower() == "cookie"), None)
                merged = merge_cookie_header(
                    upstream_headers.get(existing_key, "") if existing_key else "",
                    borrowed,
                )
                if existing_key:
                    del upstream_headers[existing_key]
                upstream_headers["cookie"] = merged

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

        # x-bare-headers is the OTHER copy of upstream.headers — the client
        # rebuilds the page-visible Response from this blob, not from our
        # direct HTTP response. Same lie as the direct headers had before
        # the previous fix: content-encoding/content-length here still
        # describe the compressed body httpx already decoded, so the client
        # decompresses the (already-plain) bytes a second time and the page
        # renders as garbage. Strip them from this copy too.
        remote_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in {"content-encoding", "content-length"}}
        response_headers = {name: remote_headers[name] for name in pass_headers if name in remote_headers}
        response_headers["x-bare-status"] = str(upstream.status_code)
        response_headers["x-bare-status-text"] = upstream.reason_phrase or ""
        response_headers["x-bare-headers"] = json.dumps(remote_headers)

        status = upstream.status_code if upstream.status_code in pass_status else 200
        return Response(content=upstream.content, status_code=status, headers=response_headers)

    @api.websocket("/{token}/v3/")
    async def ws_tunnel(websocket: WebSocket, token: str):
        from src.api.identity import decode_identity_jwt

        if not decode_identity_jwt(token):
            await websocket.close(code=4401)
            return

        await websocket.accept()

        try:
            handshake = json.loads(await websocket.receive_text())
            if handshake.get("type") != "connect":
                raise ValueError("first message must be type=connect")
            remote_url = handshake["remote"]
            protocols = handshake.get("protocols") or []
            fwd_headers = handshake.get("headers") or {}
        except Exception as exc:
            await websocket.close(code=1002, reason=str(exc)[:120])
            return

        import websockets

        try:
            remote_ws = await websockets.connect(
                remote_url,
                subprotocols=protocols or None,
                additional_headers=fwd_headers,
                open_timeout=15,
            )
        except Exception as exc:
            await websocket.close(code=1011, reason=f"connect failed: {exc}"[:120])
            return

        await websocket.send_text(json.dumps({
            "type": "open",
            "protocol": remote_ws.subprotocol or "",
            "setCookies": [],
        }))

        async def client_to_remote():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        await remote_ws.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await remote_ws.send(msg["bytes"])
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                await remote_ws.close()

        async def remote_to_client():
            try:
                async for message in remote_ws:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)
            except Exception:
                pass
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass

        await asyncio.gather(client_to_remote(), remote_to_client(), return_exceptions=True)

    return api
