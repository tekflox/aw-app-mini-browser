"""Mini Browser's piloted-browser MCP — the agent-facing tool surface.

Ported from ``tekflox/aw-app-devctl``'s ``mcp_server/devctl_browser.py``:
wraps ``mini_browser_app.cdp`` (CDP control of the shared ``aw-app-browser``
container) as MCP tools so an agent can navigate, click, type, press keys,
scroll, evaluate/inject JS, and screenshot. No dependency on the browser
being active — every call goes through ``ensure_browser()``, which starts the
container and opens a page if needed.

Registration: wired into the aw-workspace mcp-gateway via this app's
``mcp.json`` (``contributes.mcp`` in ``aw-app.json`` signals it). The gateway
spawns this with ``cwd`` set to the app root so `mini_browser_app.cdp`
imports cleanly.

Note: this package is named ``mcp_server`` (not ``mcp``) specifically to
avoid shadowing the installed ``mcp`` SDK package (FastMCP) — a directory
named ``mcp`` next to this file would resolve first on ``sys.path`` and
break the `from mcp.server.fastmcp import FastMCP` import below.

A screenshot taken through this tool is written to disk *inside the
mcp-gateway container* — a different filesystem from the workspace's own, so
its path isn't readable by an agent running against the workspace checkout.
To fetch actual screenshot bytes, use this app's HTTP twin instead:
``GET /api/apps/mini-browser/browser/screenshot`` (a Tier-1 route, which
shares the workspace's filesystem — see ``mini_browser_app/routes.py``).

``browser_screenshot_view`` is the odd one out: it screenshots this
window's OWN ``/view`` iframe (via the ``devctl`` app's side-container-free
Playwright renderer), not the CDP-piloted ``aw-app-browser``. This stdio
process was checked to have no reachable credentials for the workspace's
own HTTP API (unlike ``aw-app-browser:9223``, which is plain container-to-
container CDP, ``AW_WORKSPACE_API_KEY``/``AW_WORKSPACE_API_URL`` are minted
only inside the workspace process and never reach this container — see
``aw-app-presentations``'s abandoned stdio-callback attempt for the same
wall), so it can only confirm the target and point the caller at
``GET /api/apps/mini-browser/view/screenshot`` for the actual bytes.

``minibrowser_*`` tools (as opposed to the ``browser_*`` ones above) are a
THIRD, different piloting surface — Playwright-style control of a REAL,
already-open Mini Browser window in the user's own browser tab, via
``devctl``'s tab relay + a ``postMessage`` bridge (``mini_browser_app/
pilot.py``, ``/pilot/*`` routes). Same credential wall as
``browser_screenshot_view``: these are thin pointers at the HTTP routes
that do the actual work, not direct actors.

Run: `python -m mcp_server.mini_browser_browser` (stdio).
"""

from __future__ import annotations

import os
import sys
import time

# Allow running from the app root so `mini_browser_app` is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mini_browser_app.cdp import client  # noqa: E402

mcp = FastMCP("mini-browser")

_SHOT_DIR = os.environ.get("MINI_BROWSER_SHOT_DIR", "/tmp/mini-browser")


def _save_png(png: bytes) -> str:
    os.makedirs(_SHOT_DIR, exist_ok=True)
    path = os.path.join(_SHOT_DIR, f"shot-{int(time.time()*1000)}.png")
    with open(path, "wb") as f:
        f.write(png)
    return path


@mcp.tool()
async def browser_screenshot() -> str:
    """Capture the live browser screen. Returns a PNG file path."""
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_current() -> dict:
    """Current page title + URL."""
    return await client.current()


@mcp.tool()
async def browser_screenshot_view(url: str | None = None) -> dict:
    """Screenshot the URL this window's OWN view last loaded (or ``url``
    if given) — no side container, no CDP. This tool cannot fetch the PNG
    itself (this stdio process has no credentials for the workspace's own
    API — see the aw-mini-browser skill); it just confirms the target and
    tells the caller where to fetch bytes from.
    """
    return {
        "target": url or "(last URL loaded in this window's /view)",
        "fetch_png_from": "GET /api/apps/mini-browser/view/screenshot"
        + (f"?url={url}" if url else ""),
    }


@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """Navigate the browser to a URL (starts the browser if it's off)."""
    await client.navigate(url)
    return {"ok": True, "url": url}


@mcp.tool()
async def browser_eval(js: str):
    """Run JS in the page and return its value — read/modify the DOM."""
    return await client.evaluate(js)


@mcp.tool()
async def browser_inject(js: str) -> dict:
    """Inject a script that runs now and on every future document load."""
    await client.inject(js)
    return {"ok": True}


@mcp.tool()
async def browser_click(x: float, y: float, double: bool = False) -> str:
    """Click at CSS-pixel coordinates. Returns a screenshot path."""
    await client.click(x, y, double)
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_type(text: str, submit: bool = False) -> str:
    """Type into the focused field (click it first). Returns a screenshot path."""
    await client.type_text(text)
    if submit:
        await client.key("Enter")
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_key(key: str) -> str:
    """Press a named key (Enter, Tab, Escape, ArrowDown, ...). Returns a screenshot path."""
    await client.key(key)
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_scroll(dy: int = 300) -> str:
    """Wheel-scroll by dy pixels. Returns a screenshot path."""
    await client.scroll(dy)
    return _save_png(await client.screenshot())


_PILOT_NOTE = (
    "This stdio process has no credentials for the workspace's own HTTP "
    "API, so it can't make this call itself — fetch this route yourself "
    "with the workspace's usual X-Api-Key pattern (see the "
    "how-an-agent-sends-a-screenshot workspace memory / aw-mini-browser skill)."
)


@mcp.tool()
async def minibrowser_status() -> dict:
    """Playwright-style pilot of a REAL, already-open Mini Browser window
    (via devctl's tab relay — NOT the CDP-piloted aw-app-browser the
    browser_* tools above use). Returns the target HTTP route for
    fetching {url, status, engineReady} of that live window; 502 there
    means no Mini Browser window is currently open in a connected tab.
    """
    return {"http_route": "GET /api/apps/mini-browser/pilot/status", "note": _PILOT_NOTE}


@mcp.tool()
async def minibrowser_navigate(url: str) -> dict:
    """Navigate a REAL, already-open Mini Browser window to `url` (via
    devctl's tab relay). The window must already be open in a connected
    tab — this cannot open it for you. Fetch the target route to act.
    """
    return {
        "http_route": "POST /api/apps/mini-browser/pilot/navigate",
        "body": {"url": url},
        "note": _PILOT_NOTE,
    }


@mcp.tool()
async def minibrowser_eval(js: str) -> dict:
    """Run JS inside the page currently loaded in a REAL, already-open
    Mini Browser window's iframe (the proxied site itself, not the
    toolbar) and return its value.
    """
    return {
        "http_route": "POST /api/apps/mini-browser/pilot/eval",
        "body": {"js": js},
        "note": _PILOT_NOTE,
    }


@mcp.tool()
async def minibrowser_click(x: float, y: float) -> dict:
    """Click at CSS-pixel coordinates within a REAL, already-open Mini
    Browser window's currently loaded page.
    """
    return {
        "http_route": "POST /api/apps/mini-browser/pilot/click",
        "body": {"x": x, "y": y},
        "note": _PILOT_NOTE,
    }


@mcp.tool()
async def minibrowser_type(text: str) -> dict:
    """Type into whatever's focused (click a field first) in a REAL,
    already-open Mini Browser window's currently loaded page.
    """
    return {
        "http_route": "POST /api/apps/mini-browser/pilot/type",
        "body": {"text": text},
        "note": _PILOT_NOTE,
    }


if __name__ == "__main__":
    mcp.run()
