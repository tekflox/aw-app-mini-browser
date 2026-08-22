# Mini Browser

Mini Browser adds a lightweight web browser window to an AW Workspace. It is designed for quick page checks without leaving the workspace.

## What It Does

- Opens a simple browser window inside the workspace.
- Includes a URL bar plus back, forward, reload, and home controls.
- Loads pages through a workspace proxy when a site blocks normal embedding.
- Lets the default home page be configured.
- Contributes a `mini-browser` MCP tool (`browser_navigate`, `browser_screenshot`,
  `browser_current`, `browser_click`, `browser_type`, `browser_key`,
  `browser_scroll`, `browser_eval`, `browser_inject`) so an agent can pilot the
  shared `aw-app-browser` container the same way `aw-app-devctl` does — the
  browser a human watches over noVNC and the one an agent drives are the same
  instance.
- Also contributes `browser_screenshot_view`, a different kind of tool: it
  screenshots this window's OWN iframe (whatever URL a human last typed into
  it), with no side container at all — rendering is delegated to the
  `devctl` app's throwaway in-process Playwright renderer (`POST
  /render/screenshot`). Optional soft dependency: if `devctl` isn't
  installed, every other Mini Browser feature keeps working, only this path
  502s.
- `/view`'s iframe runs a real rewriting proxy (a vendored Ultraviolet +
  this app's own Bare Server v3), not a header-stripping fetch — real
  navigation, real cookies, correct CSS on JS-heavy sites. A "Dev" button
  next to Go opens a Requests/Console side panel.
- A third tool set, `minibrowser_status`/`_navigate`/`_eval`/`_click`/`_type`,
  is Playwright-style remote control of a REAL, already-open Mini Browser
  window in the user's own browser tab (via `devctl`'s tab relay) — not a
  piloted or headless browser at all. Requires the window to already be
  open somewhere with devctl's `[dev]` toggle on; can't open it for you.

## Why Use It

Use this app when you need a quick in-workspace way to view a page, inspect a link, or keep a lightweight browser beside other workspace tools. It is best for simple browsing and fast checks. Use its MCP tool when an agent needs to drive a real browser and prove it with a screenshot.

## How To Use It

Install the app, open Mini Browser from the workspace navigation, and enter a URL. Use the home setting to choose the page it should open by default.

An agent calls the `mini-browser` MCP tool to act (e.g. `browser_navigate`),
then fetches screenshot bytes back through this app's own HTTP route —
`GET /api/apps/mini-browser/browser/screenshot` — rather than the MCP tool's
own `browser_screenshot`, because a stdio MCP server runs inside the
mcp-gateway container and its output isn't visible on the workspace
filesystem.

## What It Delivers

The app gives AW Workspace a compact browsing surface. It is useful when a full browser session is unnecessary but a web page still needs to be visible inside the workspace.
