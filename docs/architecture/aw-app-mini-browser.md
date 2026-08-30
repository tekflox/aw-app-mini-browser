---
repo: architecture
path: docs/architecture/aw-app-mini-browser.md
source: generated
edited: false
checksum: sha256:1770a8a424cc819fe04ce3d6669afc4bc74c6a1f3d1e1f7b84c2d928eb3463ae
---
# Mini Browser

- **repo**: aw-app-mini-browser
- **layer**: app
- **technologies**: python, react
- **health** (derived): planned

In-app web browser with a real rewriting proxy — a vendored Ultraviolet (AGPL-3.0) intercepted client-side by a service worker, backed by this app's own TompHTTP Bare Server v3 (written from the open spec, no Node/Wisp/new process). Ships a resizable dev panel (Requests/Console) next to the Go button. Three independent MCP tool sets: browser_* pilots the shared aw-app-browser container over CDP (ported from aw-app-devctl); browser_screenshot_view renders this window's own iframe via devctl's side-container-free Playwright; minibrowser_* is Playwright-style remote control of a REAL, already-open Mini Browser window via devctl's tab relay + a postMessage bridge — not a piloted or headless browser at all.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/mini-browser
- `other` → **aw-app-devctl** — GET /view/screenshot and the browser_screenshot_view MCP tool delegate to devctl's POST /render/screenshot (a side-container-free Playwright renderer)

## MCP tools
_none exposed_

## Requirements
### Só os cabeçalhos que impedem o enquadramento são removidos, e só do documento de topo
- Given a UI exibe a página dentro de um iframe, e o site de origem manda X-Frame-Options e CSP que proíbem exatamente isso
- When a resposta upstream é repassada filtrando o conjunto bloqueado (repos/aw-app-mini-browser/mini_browser_app/routes.py::build_routes.proxy:57, contra _BLOCKED_RESPONSE_HEADERS:39)
- Then saem x-frame-options, as duas formas de content-security-policy, e também content-length, content-encoding e transfer-encoding — os três últimos por razão diferente e igualmente necessária: o corpo muda de tamanho quando o &lt;base&gt; é injetado, e o httpx já entregou o conteúdo decodificado, então repassar os cabeçalhos originais descreveria um corpo que não é mais o que está sendo enviado. Só o documento de topo precisa disso; sub-recursos não estão sendo enquadrados
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-mini-browser/tests/test_routes.py` (passing)

### Um &lt;base&gt; injetado faz os sub-recursos carregarem direto da origem
- Given a página chega por um proxy cujo caminho não tem relação com a URL original, então todo caminho relativo dentro dela apontaria para o lugar errado
- When o HTML é remendado antes de ser devolvido (repos/aw-app-mini-browser/mini_browser_app/routes.py:77-92)
- Then um &lt;base href="&lt;url final após redirects&gt;"&gt; entra logo depois do &lt;head&gt;, ou na frente do documento quando não há head, e a meta tag de CSP embutida no HTML é removida — o href usa upstream.url e não a URL pedida, de propósito, porque depois de um redirect é o destino final que define de onde os relativos resolvem. É explicitamente um remendo por regex e não um reescritor de URLs completo: serve para site estático ou simples, e não se garante para SPA pesada de JS com checagem anti-iframe
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-mini-browser/tests/test_routes.py` (passing)

### Só http e https são buscáveis pelo proxy
- Given a URL alvo vem inteira do cliente, num parâmetro de query
- When o esquema é conferido antes de qualquer requisição de saída (repos/aw-app-mini-browser/mini_browser_app/routes.py:59-60)
- Then qualquer coisa que não comece com http:// ou https:// vira 400 sem que o servidor busque nada — a checagem vem antes da chamada, que é o único lugar onde ela vale, e barra de saída esquemas como file:// que fariam o processo servir arquivos locais através de uma rota pensada para páginas web. Falha de rede vira 502 (routes.py:71-72), separando "você pediu errado" de "o destino não respondeu"
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-mini-browser/tests/test_routes.py` (passing)

### Erro do browser pilotado vira 502, e a tool MCP e a rota HTTP são gêmeas
- Given as rotas /browser/* dirigem o container CDP compartilhado, e o servidor MCP stdio roda no container do gateway, que não vê o filesystem do runner do agente
- When uma chamada ao CDP falha dentro da guarda comum (repos/aw-app-mini-browser/mini_browser_app/routes.py::build_routes._guard:102)
- Then o erro sai como 502 e não como 500 — 500 diz "este app quebrou", 502 diz "o browser lá atrás quebrou", e a distinção é o que direciona o diagnóstico ao container certo. O par MCP/HTTP é deliberado: o agente chama a tool MCP para agir e busca os bytes (um screenshot) pela rota HTTP Tier-1, que compartilha o filesystem que o runner enxerga
- intended_status: `not_implemented` · derived health: `not_implemented`
- tests: `repos/aw-app-mini-browser/tests/test_routes.py` (passing)
