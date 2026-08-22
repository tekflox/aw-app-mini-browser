# Vendored files — do not hand-edit

| Path | From | Version | License |
|---|---|---|---|
| `uv.bundle.js`, `uv.client.js`, `uv.handler.js`, `uv.sw.js` | `@titaniumnetwork-dev/ultraviolet` | 3.2.10 | AGPL-3.0 (`licenses/ultraviolet.LICENSE`) |
| `baremux/index.js`, `baremux/worker.js` | `@mercuryworkshop/bare-mux` | 2.1.9 | MIT (`licenses/bare-mux.LICENSE`) |
| `bare-module3/index.mjs` | `@mercuryworkshop/bare-as-module3` | 2.2.5 | LGPL-3.0 (`licenses/bare-as-module3.LICENSE`) — **PATCHED, see below** |

Otherwise unmodified, straight from each npm package's `dist/`.
`uv.config.js`, `sw.js`, and `devpanel-inject.js` in this same directory
are **this app's own files**, not vendored — that's the
customization/integration point, kept separate on purpose so an upstream
update is a clean file swap.

## `bare-module3/index.mjs` — one deliberate patch

`ClientV3.request()` (this library's own code, unchanged) hardcodes
`credentials: "omit"` on every fetch to the Bare Server — confirmed live,
no cookie, no `Authorization` header ever reaches `bare_server.py`. That
collides with this workspace's edge tunnel
(`aw-backend/src/api/routes/workspace_tunnel_proxy.py`), which requires
*some* credential-shaped header/cookie to merely be **present** before
forwarding a request at all — `X-Api-Key`, checked for presence only,
never validity at that layer (an invalid key still 401s one hop in, at
the workspace's own `require_identity`). Without any header at all, the
edge rejects the request before it ever reaches this app, full stop —
confirmed by testing with a garbage-but-present key (200) vs. no header
at all (401, edge-shaped `{"error":...}` body, not this app's own
`{"detail":...}` shape).

Patch (in `createBareHeaders()`): adds a **fixed placeholder**
`X-Api-Key: aw-mini-browser-bare-relay` header — NOT the real workspace
API key, which must never reach client-side JS. It exists purely to
satisfy the edge's presence check; `bare_server.py` ignores this header
entirely and authenticates via the real identity JWT already embedded in
the request path instead (see `routes.py::view()` /
`bare_server.py`'s own docstring). Same shape as this codebase's own
`_is_presentation_share_link` carve-out: a credential the edge can't
verify, verified for real one hop in.

LGPL-3.0 permits this modification; corresponding source is the original
npm package (`npm pack @mercuryworkshop/bare-as-module3@2.2.5`) plus this
one-hunk diff, both documented here rather than shipped as a separate
patch file.

To bump a version: re-download the package (`npm pack <name>@<version>`),
replace the listed files 1:1, update this table, re-run this app's test
suite, and manually verify a real navigation still works (`aw-mini-browser`
skill has the checklist).

## Licensing note

Ultraviolet itself is AGPL-3.0. Its network-copyleft clause is triggered by
*offering the software's functionality to users over a network* — relevant
for a public-facing deployment serving third parties, not obviously for a
private workspace operated and used by its own owner. This is a real legal
fact to be aware of, not a call this file makes for you.
