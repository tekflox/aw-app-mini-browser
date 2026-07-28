# aw-app-mini-browser

Decoupled app for aw-workspace, per the
[Decoupled Apps Framework ADR](https://github.com/tekflox/agentic-workspace/blob/main/docs/knowledge_base/docs/architecture/decoupled-apps-framework.md)
(`aw-app.json` manifest schema v1). A small in-app web browser: URL bar,
back/forward/reload/home, an iframe, and a server-side proxy that strips
`X-Frame-Options` / CSP `frame-ancestors` headers so sites that would
otherwise refuse to be framed can still be viewed inside AW.

Same pattern as `tekflox/aw-app-whiteboard` / `aw-app-git` /
`aw-app-presentations`: Tier-1 **inprocess** app — a FastAPI sub-app built
by `mini_browser_app/routes.py` and mounted at `/api/apps/mini-browser` via
`ctx.routes.register` (`routes:register` permission), plus a declarative
window (`windows/main.json`, an `iframe` widget pointing at this app's own
`GET /view`) and a workspace-nav entry.

## Status

Validated as a standalone prototype first (`agentic-workspace/src/custom_apps/mini-browser`,
proxy tested against `https://example.com` — 200, headers stripped,
`<base>` injected) before porting onto this framework's manifest +
`ctx.routes` shape. `tests/test_routes.py` covers the viewer shell, the
proxy's header-stripping (mocked HTTP, no live network in CI), and the
window-spec/route consistency check (same pattern as the sibling apps).

Not yet done: actual **install** into a running aw-workspace (this repo
existing + CI'd to the marketplace is a separate step from being installed
— see the apps framework's reconciler/catalog model).

## Endpoints (mounted at `/api/apps/mini-browser`)

- `GET /view` — the browser UI shell.
- `GET /proxy?url=<absolute-url>` — fetches `url` server-side, strips
  blocking headers, injects a `<base>` tag so the page's own relative
  links/resources resolve straight back to the origin (not through the
  proxy) — only the top-level document needs its blocking headers
  stripped, sub-resources aren't being framed.

## Known limitation

This is intentionally a simple regex-based HTML patch, not a full
URL-rewriting proxy (Ultraviolet/Rammerhead-style). Works well for
static/simple sites; JS-heavy SPAs with `window.top !== window.self`
anti-iframe checks or strict per-resource CSP may still fail.

## Local test

```
.venv/aw/bin/python -m pytest tests/test_routes.py
.venv/aw/bin/python tests/validate_manifest.py
```
