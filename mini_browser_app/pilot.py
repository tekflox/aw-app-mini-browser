"""Pilots a REAL, already-open Mini Browser window in the user's own
browser tab — not a piloted CDP browser, not a headless one. Reuses the
`devctl` app's tab relay (``POST /api/apps/devctl/eval``, a WebSocket-based
channel into whichever real tab has the ``[dev]`` toggle on) to run JS in
the TOP page (the AW workspace SPA), which then ``postMessage``s into this
app's own ``/view`` iframe — the one channel that crosses the cross-origin
boundary between the SPA (``workspace.<domain>``) and this app's routes
(``api.workspace.<domain>``). See ``viewer.py``'s "Remote pilot" section
for the receiving end of this protocol.

Why not call devctl directly from the MCP tool instead of through an HTTP
route here? Confirmed dead end this session (browser_screenshot_view hit
the same wall): the mcp-gateway container that runs the stdio MCP process
has no credentials for this workspace's own identity-gated HTTP API. This
module's routes work because they're called from THIS Tier-1 app's own
in-process code — a loopback call to devctl satisfies its `/eval` and
`/tabs` ``local_paths`` bypass (127.0.0.1 caller, no identity needed) —
the agent hits these routes directly with its own credentials instead
(same pattern as ``routes.py``'s ``/view/screenshot``).
"""

from __future__ import annotations

import json
import os

import httpx

_MINI_BROWSER_IFRAME_MARKER = "/api/apps/mini-browser/view"


def js_str(value: str) -> str:
    """A Python string safely encoded as a JS string literal — JSON's
    string syntax is a strict subset of JS's, so json.dumps is exact."""
    return json.dumps(value)


def js_num(value) -> str:
    return json.dumps(float(value))


def _devctl_base() -> str:
    return f"http://127.0.0.1:{os.environ.get('AW_PORT', '9030')}/api/apps/devctl"


def _relay_js(cmd_js: str) -> str:
    """Wraps a JS expression (that builds the ``{cmd, ...}`` payload) into
    the full relay script: find the iframe, postMessage the command, wait
    for the matching ``mb-pilot-result`` reply, return it. Runs as the body
    of an async function (see ``devctl_app/relay.py::evalCode``)."""
    return f"""
        var iframe = Array.from(document.querySelectorAll('iframe'))
          .find(function(f) {{ return f.src && f.src.indexOf({json.dumps(_MINI_BROWSER_IFRAME_MARKER)}) !== -1; }});
        if (!iframe) return {{ error: 'mini-browser window not found — ask the user to open it' }};
        var id = Math.random().toString(36).slice(2);
        var resultPromise = new Promise(function(resolve) {{
          function onMsg(e) {{
            if (e.data && e.data.type === 'mb-pilot-result' && e.data.id === id) {{
              window.removeEventListener('message', onMsg);
              resolve(e.data);
            }}
          }}
          window.addEventListener('message', onMsg);
          setTimeout(function() {{ window.removeEventListener('message', onMsg); resolve({{ error: 'timeout waiting for mini-browser' }}); }}, 12000);
        }});
        iframe.contentWindow.postMessage(Object.assign({cmd_js}, {{ type: 'mb-pilot-cmd', id: id }}), new URL(iframe.src).origin);
        return await resultPromise;
    """


async def run_pilot_command(cmd_js: str, timeout: float = 15.0) -> dict:
    """POSTs the relay script to devctl's tab relay and returns its parsed
    JSON reply — ``{"ok": true, "result": {...}}`` or ``{"ok": false,
    "error": "..."}`` (no connected tab, tab-side exception, etc)."""
    async with httpx.AsyncClient(timeout=timeout + 5.0) as client:
        resp = await client.post(
            f"{_devctl_base()}/eval",
            json={"code": _relay_js(cmd_js), "timeout": timeout},
        )
    return resp.json()
