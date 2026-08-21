---
name: aw-mini-browser
description: What the Mini Browser app is and how its MCP tools (browser_navigate/click/type/screenshot/...) actually work — it does NOT drive its own iframe, it pilots the separate shared `aw-app-browser` (noVNC) container over CDP, the same instance a human watches in the "Browser" app window. One exception — `browser_screenshot_view` screenshots the window's OWN iframe via the `devctl` app, no side container. Use whenever asked to pilot a browser for quick assisted navigation/debugging, when explaining what Mini Browser is, or when a `mini-browser` MCP call errors with "aw-app-browser not reachable over CDP".
---

# aw-mini-browser — lightweight, human-visible browser piloting

Mini Browser (`aw-app-mini-browser`, Tier-1, in-process) bundles **two
independent surfaces** that are easy to conflate — know which one you're
touching.

## 1. The window's own iframe — passive, EXCEPT for one screenshot path

The Mini Browser window (`windows/main.json`) is a declarative `iframe`
widget pointed at this app's own `GET /view` route
(`mini_browser_app/viewer.py`), which is itself proxied through
`mini_browser_app/routes.py` — a server-side proxy that strips
`X-Frame-Options`/CSP so sites that would otherwise refuse to be framed
still render inside the workspace. This is a URL-bar-and-iframe page viewer.
**No MCP tool clicks/types into this iframe's content** — but one tool CAN
see it: `browser_screenshot_view` (see below).

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

## 3. `browser_screenshot_view` — screenshots the WINDOW's OWN iframe, no CDP, no container

The one tool that breaks the "surface 1 is passive" rule above. It doesn't
touch `aw-app-browser` at all — it screenshots whatever raw target URL the
window's `/view` iframe last loaded (tracked server-side in
`mini_browser_app/routes.py`'s `_last_url`, set every time `/proxy` fires),
or an explicit `url` argument.

Rendering is delegated to the **`devctl`** app's `POST
/render/screenshot` — a throwaway, in-process Playwright chromium (ported
behaviorally from `aw-app-whiteboard`'s `screenshot_url`) that renders one
URL and closes. No side container, no CDP, no dependency on
`aw-app-browser` being up. This is a **soft dependency**: declared in
`aw-app.json`'s `dependencies.apps` as `required: false` — if `devctl`
isn't installed, everything else in Mini Browser still works; only this one
path 502s.

The stdio MCP tool itself cannot fetch the PNG (confirmed live: the
mcp-gateway container has no `AW_WORKSPACE_API_KEY`/`AW_WORKSPACE_API_URL` —
those are minted only inside the workspace process and never propagated
into a Tier-2 container's env; `aw-app-presentations` hit and documented
the identical wall). So `browser_screenshot_view` just confirms the target
and points at the real fetch route:

```python
import os, httpx
from src.cli import local_client
from src.api.workspace_api_key import ENV_VAR_NAME, HEADER_NAME

url = local_client.base_url().rstrip('/') + '/api/apps/mini-browser/view/screenshot'
key = os.environ.get(ENV_VAR_NAME) or local_client._read_env_value(ENV_VAR_NAME)
png = httpx.get(url, headers={HEADER_NAME: key}, timeout=90).content   # image/png
# or ?url=https://... to override the last-navigated URL
```

Because this renders the raw external URL directly (not mini-browser's own
gated `/proxy` URL), there is no API key to leak to the target and no
own-origin auth dance to get wrong — unlike `aw-app-whiteboard`'s version of
this same function, which screenshots its OWN identity-gated pages and
therefore does need one.

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
