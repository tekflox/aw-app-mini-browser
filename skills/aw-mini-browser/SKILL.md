---
name: aw-mini-browser
description: What the Mini Browser app is — THREE independent piloting surfaces easy to conflate. (1) its OWN window runs a real rewriting proxy (vendored Ultraviolet + this app's Bare Server v3) with a Dev panel next to Go. (2) `browser_*` MCP tools pilot the separate shared `aw-app-browser` (noVNC) container over CDP. (3) `minibrowser_*` MCP tools are Playwright-style remote control of a REAL, already-open Mini Browser window via devctl's tab relay — not a piloted/headless browser at all. Use whenever asked to pilot a browser, explain what Mini Browser is, debug the proxy/dev-panel/pilot, or when a `mini-browser` MCP call errors.
---

# aw-mini-browser — a real rewriting proxy in the window, CDP piloting via MCP

Mini Browser (`aw-app-mini-browser`, Tier-1, in-process) bundles **two
independent surfaces** that are easy to conflate — know which one you're
touching. As of the Ultraviolet integration, surface 1 stopped being
passive — read this before assuming the old "just a header-stripping
iframe" model still holds.

## 1. The window's own iframe — a real rewriting proxy, not just a stripped fetch

The Mini Browser window (`windows/main.json`) is a declarative `iframe`
widget pointed at this app's own `GET /view` route
(`mini_browser_app/viewer.py`). That page now runs a vendored
**Ultraviolet** (`mini_browser_app/static/uv/`, AGPL-3.0 — see
`static/uv/VENDORED.md`) intercepted client-side by a Service Worker
(`static/uv/sw.js`), backed by this app's own hand-written **Bare Server
v3** (`mini_browser_app/bare_server.py`, written from the open
[TompHTTP spec](https://github.com/tomphttp/specifications), no Node/Wisp,
no new process). This means real navigation — the proxied page's own JS
runs with a genuinely non-opaque origin check passing (no more Google
homepage falling back to unstyled buttons because `location.href` didn't
match), and cookies persist (Ultraviolet manages its own per-origin cookie
jar in IndexedDB inside the service worker).

The old `/proxy` route (regex HTML patch + `<base>` tag, "not guaranteed
for JS-heavy SPAs") still exists in `routes.py` but **`/view` no longer
uses it**. `view/screenshot`'s `_last_url` bookkeeping now comes from a
new `GET /track-nav` ping fired fire-and-forget by `/view`'s own JS on
every navigation, not from `/proxy` anymore.

**REQUIRED post-install step: `auth_required: false`.** Confirmed live
with a real logged-in session: `bare-as-module3` (the vendored transport)
hardcodes `credentials: "omit"` on every fetch to the Bare Server — no
cookie, no `Authorization` header, ever reaches `bare_server.py`, no
matter what. The workspace's normal cookie-based `IdentityGuard` can
therefore never pass for `/bare/*`, so this app's `auth_required` config
must be `false` (Workspace → Apps → mini-browser → settings →
"Authentication required" toggle off) for navigation to work AT ALL — a
fresh install 401s at `/bare/*` and Mini Browser hangs on "Starting
engine…" forever until this is flipped. This is NOT "no auth" for the
app as a whole: `routes.py::view()` and `bare_server.py`'s data endpoint
each enforce identity themselves in this mode (`view()` 401s without a
valid cookie/bearer; the Bare Server's data endpoint 401s without a
valid token in the URL path — see below). Only `/uv/*` (static JS,
harmless) and `/bare/`'s bare info endpoint are genuinely open.

**How the Bare Server stays closed to strangers despite no cookie
reaching it**: since the header/cookie channel is closed off by the
library, the ONE thing this app still controls is the *base server URL*
it hands to `bare-as-module3`'s constructor. `routes.py::view()` extracts
the caller's own raw identity JWT (same `aw_id_jwt` cookie / `Bearer`
header the rest of the workspace already uses — re-verified via
`decode_identity_jwt` straight from `src.api.identity`, no new
verification logic invented) and embeds it into the page
(`__IDENTITY_TOKEN__` in `viewer.py`). The page then calls
`setTransport(..., [origin + '/bare/' + token + '/'])`, so every
subsequent Bare Server request lands on `/bare/{token}/v3/`, and
`bare_server.py`'s data endpoint re-verifies that token before doing
anything. Without a valid, real identity token embedded by a legitimate
`/view` load, `/bare/*` refuses to relay anything — so it does NOT
become an open SSRF/abuse relay just because `auth_required` is off.

**A THIRD, separate gate exists one hop further out — the workspace's
edge tunnel** (`aw-backend/src/api/routes/workspace_tunnel_proxy.py`, a
different repo entirely). It requires SOME credential-shaped
header/cookie to be merely *present* before forwarding a request at
all, checked before the request ever reaches this workspace's process —
`credentials:"omit"` means no cookie gets there either, so even with
`auth_required:false` correctly set, every real proxied request 401'd
at the edge with a distinct `{"error":...}` body (not this app's own
`{"detail":...}` shape — that's the tell for which layer actually
rejected it). Confirmed by testing a garbage-but-present `X-Api-Key`
(200, forwarded) vs. no header at all (401, edge). Fixed by patching
`static/uv/bare-module3/index.mjs` to always send a **fixed placeholder**
`X-Api-Key` — not the real key, which must never reach client-side JS —
purely to satisfy the edge's presence check; see `VENDORED.md` for the
full patch and reasoning. Do NOT "fix" this by routing traffic through
`aw-app-proxy` — that app is an unrelated cookie-sync/CONNECT-tunnel
helper for the piloted `aw-app-browser`, not an edge-auth bypass (checked
live; no carve-out for it exists in `workspace_tunnel_proxy.py`).

**Service Worker registration works inside this exact sandboxed iframe**
(`sandbox="allow-scripts allow-forms allow-same-origin"` in
`aw-workspace-ui/src/components/AppWindow.jsx`) — confirmed both by
reading the SW spec's actual `Register` algorithm (the only thing that
blocks it is an *opaque* origin, and `allow-same-origin` prevents that)
and by a live Playwright test. Don't re-derive or doubt this from a vague
memory of "sandboxed iframes can't run service workers" — that rule does
not exist for this token combination.

**Don't wait on `navigator.serviceWorker.ready` in `startEngine()`** —
it resolves only once a worker CONTROLS the current document, and
`/view` is deliberately OUTSIDE the SW's own scope
(`__uv$config.prefix`, i.e. `uv/service/`), so `.ready` hangs forever
here even once the registration is genuinely `active`. Confirmed live
(bootstrap stuck on "Starting engine…" indefinitely, no error, `.ready`
never settling) despite `getRegistration()` already showing
`active.state === "activated"`. `viewer.py` instead awaits the
registration object's own `installing`/`waiting` → `statechange` →
`"activated"` transition (or does nothing if `.active` is already set).

**Dev panel**: a "Dev" button next to Go opens a slide-out side panel with
two tabs — **Requests** (every proxied request/response, from the SW's
`request`/`response` events relayed via `postMessage`) and **Console**
(console.log/warn/error from the proxied page, hooked by
`static/uv/devpanel-inject.js`, which Ultraviolet injects into every
proxied page via `uv.config.js`'s `inject` option). **No Cookies tab** —
reading Ultraviolet's internal per-origin cookie jar would mean forking
`uv.sw.js` (against the point of vendoring it unmodified) or a more
involved message-relay; scoped out, listed as a pendência.

**Known gap: no WebSocket tunnel.** The Bare Server v3 spec's WS-tunnel
handshake isn't implemented in `bare_server.py` yet — a proxied page that
opens a raw WebSocket (chat apps, live dashboards) will fail. Regular
HTTP navigation/fetch/XHR works fine.

**No MCP tool clicks/types into this iframe's content** — one tool CAN
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

## 4. `minibrowser_*` — Playwright-style pilot of a REAL, already-open window

A FOURTH surface (well, third piloting mechanism — screenshot_view isn't
really "piloting"), and the newest: `minibrowser_status`, `_navigate`,
`_eval`, `_click`, `_type`. These do NOT touch `aw-app-browser` at all —
they drive whatever Mini Browser window is *already open in a real user's
own browser tab* (their laptop, wherever), via `devctl`'s tab relay
(`POST /api/apps/devctl/eval`, `devctl_app/relay.py` in `tekflox/aw-app-devctl`) plus a
`postMessage` bridge (`mini_browser_app/pilot.py` + `viewer.py`'s "Remote
pilot" section).

**Why this needs a relay at all, and why it's a THIRD mechanism, not a
tweak to the other two**: devctl's tab relay reaches the TOP page (the AW
workspace SPA, `workspace.<domain>`), but Mini Browser's `/view` is a
same-window but DIFFERENT-ORIGIN iframe inside it (`api.workspace.<domain>`)
— `iframe.contentDocument` throws (confirmed live), so the relay's JS
can't just reach in directly. `postMessage` is the one channel that
crosses that boundary safely, so `/view` runs its own listener
(`window.addEventListener('message', ...)`, origin-checked against
`location.origin` with the `api.` prefix stripped — no hardcoded domain,
works on any workspace) and answers with `{type: 'mb-pilot-result', ...}`.

**Command targets**: `navigate` drives the OUTER toolbar (`urlBar`/`frame.src`,
same as a human typing a URL); `eval`/`click`/`type` target the INNER
proxied page (`frame.contentWindow`/`frame.contentDocument` — same-origin
now, because that's the whole point of the UV integration) — i.e. the
actual website content, not the toolbar chrome.

**Hard limitation, by design, not yet solved**: `minibrowser_navigate`
etc. **cannot open the window for you** — if no Mini Browser window is
open in ANY tab with devctl's `[dev]` toggle on, every one of these
returns `502 {"error": "mini-browser window not found — ask the user to
open it"}`. Auto-opening it would mean scripting the AW workspace SPA's
own app-launch flow via the SAME relay — not attempted yet, listed as a
pendência.

**Same credential wall as `browser_screenshot_view`**: the stdio MCP
process can't call these HTTP routes itself (mcp-gateway container has no
workspace credentials — confirmed dead end, see that tool's own
docstring), so `minibrowser_*` tools just confirm the target and point at
`POST /api/apps/mini-browser/pilot/{navigate,eval,click,type}` /
`GET .../pilot/status` for the agent to call directly with its own
`X-Api-Key`.

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
