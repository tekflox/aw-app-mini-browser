"""Browser UI shell served at ``GET /view`` (mounted under
``/api/apps/mini-browser`` by ``routes.py``). ``__HOME_URL__`` is
substituted with the app's configured ``home_url``, and
``__IDENTITY_TOKEN__`` with the caller's own raw identity JWT (extracted
and re-verified by ``routes.py::view()``), before serving.

This app's ``auth_required`` config MUST be ``false`` for this route to
be reachable at all under this design — ``view()`` enforces auth itself
(see ``bare_server.py``'s docstring for the full why). If Mini Browser
stops loading with a 401 after a fresh install, check
Workspace → Apps → mini-browser → settings → "Authentication required".

Note: no ``<form>`` submission — this shell may itself be rendered inside a
sandboxed iframe (the declarative window's ``iframe`` widget), and a
sandboxed frame without ``allow-forms`` silently blocks form submits (both
click and Enter-to-submit). Click/keydown listeners sidestep that
entirely.

Navigation is powered by a vendored Ultraviolet (``static/uv/``) — a real
rewriting proxy intercepted via a service worker, not the old
header-stripping ``/proxy`` route (still present, used by nothing here
anymore). Confirmed live that Service Worker registration works inside
this exact sandboxed iframe (``sandbox="allow-scripts allow-forms
allow-same-origin"`` in aw-workspace-ui's ``AppWindow.jsx``) — SW
registration is only blocked by an *opaque* origin, and
``allow-same-origin`` prevents that.
"""

VIEWER_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mini Browser</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #1e1f22; }
  .browser { display: flex; height: 100vh; }
  .main { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #2b2d31; border-bottom: 1px solid #1a1b1e; }
  .icon-btn { background: #3a3d42; color: #e3e5e8; border: none; border-radius: 8px; width: 36px; height: 32px; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .icon-btn:hover { background: #47494f; }
  .icon-btn:disabled { opacity: .4; cursor: default; }
  .icon-btn.active { background: #5865f2; }
  .url-row { flex: 1; display: flex; align-items: center; gap: 8px; }
  #go { width: auto; padding: 0 14px; }
  #dev-toggle { width: auto; padding: 0 12px; font-size: 12px; font-weight: 600; }
  #url-bar { flex: 1; height: 32px; border-radius: 16px; border: 1px solid #444; background: #1e1f22; color: #e3e5e8; padding: 0 14px; font-size: 14px; outline: none; }
  #url-bar:focus { border-color: #5865f2; }
  #status { font-size: 12px; color: #9aa0a6; padding: 4px 14px; min-height: 18px; background: #232428; }
  .frame-wrap { flex: 1; background: #fff; }
  #frame { width: 100%; height: 100%; border: 0; display: block; }
  #devpanel { width: 380px; flex-shrink: 0; background: #202124; border-left: 1px solid #1a1b1e; display: none; flex-direction: column; color: #e3e5e8; }
  #devpanel.open { display: flex; }
  .dp-tabs { display: flex; border-bottom: 1px solid #1a1b1e; }
  .dp-tab { flex: 1; padding: 10px; text-align: center; font-size: 12px; cursor: pointer; color: #9aa0a6; background: #2b2d31; }
  .dp-tab.active { color: #fff; background: #202124; border-bottom: 2px solid #5865f2; }
  .dp-body { flex: 1; overflow-y: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  .dp-pane { display: none; padding: 8px; }
  .dp-pane.active { display: block; }
  .dp-row { padding: 6px 4px; border-bottom: 1px solid #2a2b2f; word-break: break-all; }
  .dp-row .m { color: #7dd3fc; font-weight: 600; margin-right: 6px; }
  .dp-row .s-ok { color: #86efac; }
  .dp-row .s-err { color: #fca5a5; }
  .dp-row .lvl-warn { color: #fde68a; }
  .dp-row .lvl-error { color: #fca5a5; }
  .dp-clear { font-size: 11px; color: #9aa0a6; padding: 6px 8px; cursor: pointer; text-align: right; }
</style>
</head>
<body>
<div class="browser">
  <div class="main">
    <div class="toolbar">
      <button id="back" class="icon-btn" title="Back">&#8592;</button>
      <button id="fwd" class="icon-btn" title="Forward">&#8594;</button>
      <button id="reload" class="icon-btn" title="Reload">&#8635;</button>
      <button id="home" class="icon-btn" title="Home">&#8962;</button>
      <div class="url-row">
        <input id="url-bar" type="text" spellcheck="false" autocomplete="off" placeholder="Type a URL...">
        <button id="go" type="button" class="icon-btn">Go</button>
        <button id="dev-toggle" type="button" class="icon-btn" title="Dev panel">Dev</button>
      </div>
    </div>
    <div id="status">Starting engine…</div>
    <div class="frame-wrap"><iframe id="frame" title="Mini Browser Frame"></iframe></div>
  </div>
  <div id="devpanel">
    <div class="dp-tabs">
      <div class="dp-tab active" data-pane="requests">Requests</div>
      <div class="dp-tab" data-pane="console">Console</div>
    </div>
    <div class="dp-clear" id="dp-clear">Clear</div>
    <div class="dp-body">
      <div class="dp-pane active" id="pane-requests"></div>
      <div class="dp-pane" id="pane-console"></div>
    </div>
  </div>
</div>

<script src="uv/uv.bundle.js"></script>
<script src="uv/uv.config.js"></script>
<script src="uv/baremux/index.js"></script>
<script>
(function(){
  var HOME = "__HOME_URL__";
  // The same identity JWT that got this page served — bare-as-module3
  // hardcodes credentials:"omit" on its own fetches, so it's re-verified
  // server-side (bare_server.py) as a URL path segment instead of a
  // cookie/header, since that's the one thing this app controls.
  var IDENTITY_TOKEN = "__IDENTITY_TOKEN__";
  var frame = document.getElementById('frame');
  var urlBar = document.getElementById('url-bar');
  var status = document.getElementById('status');
  var back = document.getElementById('back');
  var fwd = document.getElementById('fwd');
  var reload = document.getElementById('reload');
  var home = document.getElementById('home');
  var go = document.getElementById('go');
  var devToggle = document.getElementById('dev-toggle');
  var devPanel = document.getElementById('devpanel');
  var paneRequests = document.getElementById('pane-requests');
  var paneConsole = document.getElementById('pane-console');

  var history = [];
  var index = -1;
  var engineReady = false;

  function normalize(raw){
    var t = (raw || '').trim();
    if (!t) return null;
    if (/^https?:\\/\\//i.test(t)) return t;
    if (/^[\\w-]+(\\.[\\w-]+)+/.test(t) && t.indexOf(' ') === -1) return 'https://' + t;
    return 'https://www.google.com/search?q=' + encodeURIComponent(t);
  }

  function proxiedUrl(url){
    return location.origin + __uv$config.prefix + __uv$config.encodeUrl(url);
  }

  function updateButtons(){
    back.disabled = index <= 0;
    fwd.disabled = index >= history.length - 1;
  }

  function navigate(url, push){
    if (!engineReady){ status.textContent = 'Engine still starting…'; return; }
    urlBar.value = url;
    status.textContent = 'Loading ' + url + '...';
    frame.src = proxiedUrl(url);
    fetch('track-nav?url=' + encodeURIComponent(url)).catch(function(){});
    if (push !== false){
      history = history.slice(0, index + 1);
      history.push(url);
      index = history.length - 1;
    }
    updateButtons();
  }

  function goFromInput(){
    var url = normalize(urlBar.value);
    if (url) navigate(url);
  }

  frame.addEventListener('load', function(){
    status.textContent = 'Ready — ' + (history[index] || '');
  });

  go.addEventListener('click', goFromInput);
  urlBar.addEventListener('keydown', function(e){
    if (e.key === 'Enter'){ e.preventDefault(); goFromInput(); }
  });
  back.addEventListener('click', function(){
    if (index > 0){ index -= 1; navigate(history[index], false); }
  });
  fwd.addEventListener('click', function(){
    if (index < history.length - 1){ index += 1; navigate(history[index], false); }
  });
  reload.addEventListener('click', function(){
    var cur = history[index];
    if (!cur) return;
    status.textContent = 'Reloading...';
    frame.src = 'about:blank';
    setTimeout(function(){ frame.src = proxiedUrl(cur); }, 30);
  });
  home.addEventListener('click', function(){ navigate(HOME); });

  // --- Dev panel -----------------------------------------------------
  devToggle.addEventListener('click', function(){
    devPanel.classList.toggle('open');
    devToggle.classList.toggle('active');
  });
  document.querySelectorAll('.dp-tab').forEach(function(tab){
    tab.addEventListener('click', function(){
      document.querySelectorAll('.dp-tab').forEach(function(t){ t.classList.remove('active'); });
      document.querySelectorAll('.dp-pane').forEach(function(p){ p.classList.remove('active'); });
      tab.classList.add('active');
      document.getElementById('pane-' + tab.dataset.pane).classList.add('active');
    });
  });
  document.getElementById('dp-clear').addEventListener('click', function(){
    paneRequests.innerHTML = '';
    paneConsole.innerHTML = '';
  });

  var pendingReq = {};
  function addRow(container, html){
    var row = document.createElement('div');
    row.className = 'dp-row';
    row.innerHTML = html;
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
    // cap history so a chatty page doesn't grow this unboundedly
    while (container.children.length > 300) container.removeChild(container.firstChild);
  }

  function escapeHtml(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function onSWMessage(event){
    var d = event.data || {};
    if (d.type === 'uv-request'){
      addRow(paneRequests, '<span class="m">' + escapeHtml(d.method) + '</span>' + escapeHtml(d.url));
    } else if (d.type === 'uv-response'){
      var ok = d.status && d.status < 400;
      addRow(paneRequests, '<span class="' + (ok ? 's-ok' : 's-err') + '">' + escapeHtml(d.status) + '</span> ' + escapeHtml(d.url));
    } else if (d.type === 'uv-console'){
      var cls = d.level === 'error' ? 'lvl-error' : (d.level === 'warn' ? 'lvl-warn' : '');
      addRow(paneConsole, '<span class="' + cls + '">[' + escapeHtml(d.level) + ']</span> ' + escapeHtml((d.args || []).join(' ')));
    }
  }

  // --- Engine bootstrap ------------------------------------------------
  // Order matters (per Ultraviolet/bare-mux docs): register the SW, THEN
  // set the transport, THEN navigate — setting the transport after the SW
  // starts intercepting is a documented race condition.
  async function startEngine(){
    if (!navigator.serviceWorker){
      status.textContent = 'Service workers unavailable (needs HTTPS or localhost) — navigation disabled.';
      return;
    }
    try {
      var registration = await navigator.serviceWorker.register('uv/sw.js', { scope: __uv$config.prefix });
      // NOT navigator.serviceWorker.ready — this page (/view) is OUTSIDE
      // the SW's own scope (__uv$config.prefix) on purpose, so `.ready`
      // (which waits for a worker controlling THIS document) never
      // resolves here. Wait on the registration's own activation instead.
      if (!registration.active){
        await new Promise(function(resolve){
          var w = registration.installing || registration.waiting;
          if (!w) { resolve(); return; }
          w.addEventListener('statechange', function(){
            if (w.state === 'activated') resolve();
          });
        });
      }
      navigator.serviceWorker.addEventListener('message', onSWMessage);

      var conn = new BareMux.BareMuxConnection('/api/apps/mini-browser/uv/baremux/worker.js');
      await conn.setTransport('/api/apps/mini-browser/uv/bare-module3/index.mjs', [
        location.origin + '/api/apps/mini-browser/bare/' + encodeURIComponent(IDENTITY_TOKEN) + '/'
      ]);

      engineReady = true;
      status.textContent = 'Ready';
      navigate(HOME);
    } catch (e) {
      status.textContent = 'Engine failed to start: ' + (e && e.message ? e.message : e);
    }
  }

  startEngine();
})();
</script>
</body>
</html>
"""
