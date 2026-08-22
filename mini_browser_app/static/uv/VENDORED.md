# Vendored files — do not hand-edit

| Path | From | Version | License |
|---|---|---|---|
| `uv.bundle.js`, `uv.client.js`, `uv.handler.js`, `uv.sw.js` | `@titaniumnetwork-dev/ultraviolet` | 3.2.10 | AGPL-3.0 (`licenses/ultraviolet.LICENSE`) |
| `baremux/index.js`, `baremux/worker.js` | `@mercuryworkshop/bare-mux` | 2.1.9 | MIT (`licenses/bare-mux.LICENSE`) |
| `bare-module3/index.mjs` | `@mercuryworkshop/bare-as-module3` | 2.2.5 | LGPL-3.0 (`licenses/bare-as-module3.LICENSE`) |

Unmodified, straight from each npm package's `dist/`. `uv.config.js`,
`sw.js`, and `devpanel-inject.js` in this same directory are **this app's
own files**, not vendored — that's the customization/integration point,
kept separate on purpose so an upstream update is a clean file swap.

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
