---
repo: architecture
path: docs/architecture/aw-app-mini-browser.md
source: generated
edited: false
checksum: sha256:b504baf422fa5a024af701ed6bd091802c0e9da7296c0355f9cab3e2eb0b9868
---
# Mini Browser

- **repo**: aw-app-mini-browser
- **layer**: app
- **technologies**: python
- **health** (derived): planned

Small in-app web browser — URL bar, back/forward/reload/home, an iframe, and a server-side proxy that strips X-Frame-Options/CSP so sites that would otherwise refuse to be framed can still be viewed inside AW. Also pilots the shared aw-app-browser container over CDP (navigate/click/type/eval/screenshot), ported from aw-app-devctl: a mini-browser-browser MCP tool wrapper is contributed for agents via mcp.json, with an HTTP twin under /browser/* for fetching screenshot bytes back onto the workspace filesystem.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/mini-browser

## MCP tools
_none exposed_

## Requirements
_none documented_
