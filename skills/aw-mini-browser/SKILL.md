---
name: aw-mini-browser
description: What the Mini Browser app is and how its MCP tools (browser_navigate/click/type/screenshot/...) actually work — it does NOT drive its own iframe, it pilots the separate shared `aw-app-browser` (noVNC) container over CDP, the same instance a human watches in the "Browser" app window. Use whenever asked to pilot a browser for quick assisted navigation/debugging, when explaining what Mini Browser is, or when a `mini-browser` MCP call errors with "aw-app-browser not reachable over CDP".
---

# aw-mini-browser — lightweight, human-visible browser piloting

Mini Browser (`aw-app-mini-browser`, Tier-1, in-process) bundles **two
independent surfaces** that are easy to conflate — know which one you're
touching.

## 1. The window's own iframe — passive, not agent-piloted

The Mini Browser window (`windows/main.json`) is a declarative `iframe`
widget pointed at this app's own `GET /view` route
(`mini_browser_app/viewer.py`), which is itself proxied through
`mini_browser_app/routes.py` — a server-side proxy that strips
`X-Frame-Options`/CSP so sites that would otherwise refuse to be framed
still render inside the workspace. This is a URL-bar-and-iframe page viewer,
nothing more. **No MCP tool controls this iframe's content** — a
`browser_click` call does not click inside it.

## 2. The `mini-browser` MCP tool — pilots a *different*, shared browser

The actual piloting surface (`mcp_server/mini_browser_browser.py` +
`mini_browser_app/cdp.py`) drives the **separate `aw-app-browser`
container** over raw CDP on `aw-app-browser:9223` — the exact same Chromium
instance a human watches live over noVNC in the standalone **"Browser"**
app window (`vnc.html`, port 7900). Ported from `tekflox/aw-app-devctl`,
itself ported from the monolith's `whiteboard_browser.py` primitives.

> "the browser the user sees (noVNC) and the browser Mini Browser's agent
> tools control are the SAME instance" — `mini_browser_app/cdp.py` docstring.

So: piloting with `mini-browser` and opening the **Browser** app window
(not Mini Browser's own window) to watch is today's correct mental model —
agent and human share one real Chromium tab, human still has the mouse/
keyboard too via noVNC. It is genuinely "the user's own browser", just not
the one rendered inside *this* app's iframe.

Tools: `browser_navigate`, `browser_click`, `browser_type`, `browser_key`,
`browser_scroll`, `browser_eval`, `browser_inject`, `browser_current`,
`browser_screenshot`.

### Screenshot bytes need the HTTP twin, not the MCP tool's own return

`browser_screenshot` (the MCP tool) writes its PNG inside the
mcp-gateway container — invisible to an agent's own filesystem. Fetch the
same screenshot through this app's Tier-1 HTTP route instead
(see [[how-an-agent-sends-a-screenshot]] for the general pattern):

```python
import os, httpx
from src.cli import local_client
from src.api.workspace_api_key import ENV_VAR_NAME, HEADER_NAME

url = local_client.base_url().rstrip('/') + '/api/apps/mini-browser/browser/screenshot'
key = os.environ.get(ENV_VAR_NAME) or local_client._read_env_value(ENV_VAR_NAME)
png = httpx.get(url, headers={HEADER_NAME: key}, timeout=90).content   # image/png
```

Write the PNG under `.tmp/` and `[[ATTACH]]` it — see the workspace's
scratch-file convention in `AGENTS.md`.

### "aw-app-browser not reachable over CDP (:9223) and could not be started"

`cdp.py::ensure_browser()` tries a best-effort container start before
giving up, but that path can silently fail (e.g. no `docker` SDK, or
`DOCKER_HOST`/`AW_PODMAN_SOCKET` unset in this process). If a
`browser_navigate`/`browser_click` call throws this error, don't just
retry it — start the container explicitly first:

```bash
aw-workspace-cli start browser
```

then retry the MCP call. Check `aw-workspace-cli apps browser --json` →
`config.auto_start` if this keeps recurring; it defaults to off.

## Why this exists instead of just using Playwright

Mini Browser is deliberately **lighter and less robust** than the
`playwright` MCP: no accessibility snapshot, no network interception, no
file upload, no stealth/anti-detection init scripts. What it buys back is
agility — a human can pull up the same live tab in one click (the
"Browser" app window) and watch an agent work, or take over the mouse
mid-task, without any handoff ceremony. Reach for it for **quick assisted
navigation and debugging** (reproduce a bug live with the user watching,
poke at a page's DOM, grab one screenshot) — reach for `playwright`
instead when you need a robust, scriptable, unattended automation (full
test flows, `browser_run_code_unsafe`, stealth login, structured
snapshots).

## Related

- [[how-an-agent-sends-a-screenshot]] — the general Tier-1-HTTP-route
  pattern this app's screenshot route follows.
- [[playwright-google-stealth]] (agentic-workspace KB) — the anti-detection
  trick Mini Browser's CDP client does *not* have; use `playwright` instead
  for anything Google/Gmail-auth-gated.
