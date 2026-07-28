"""Browser UI shell served at ``GET /view`` (mounted under
``/api/apps/mini-browser`` by ``routes.py``). ``__HOME_URL__`` is
substituted with the app's configured ``home_url`` before serving.

Note: no ``<form>`` submission — this shell may itself be rendered inside a
sandboxed iframe (the declarative window's ``iframe`` widget), and a
sandboxed frame without ``allow-forms`` silently blocks form submits (both
click and Enter-to-submit). Click/keydown listeners sidestep that
entirely.
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
  .browser { display: flex; flex-direction: column; height: 100vh; }
  .toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #2b2d31; border-bottom: 1px solid #1a1b1e; }
  .icon-btn { background: #3a3d42; color: #e3e5e8; border: none; border-radius: 8px; width: 36px; height: 32px; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .icon-btn:hover { background: #47494f; }
  .icon-btn:disabled { opacity: .4; cursor: default; }
  .url-row { flex: 1; display: flex; align-items: center; gap: 8px; }
  #go { width: auto; padding: 0 14px; }
  #url-bar { flex: 1; height: 32px; border-radius: 16px; border: 1px solid #444; background: #1e1f22; color: #e3e5e8; padding: 0 14px; font-size: 14px; outline: none; }
  #url-bar:focus { border-color: #5865f2; }
  #status { font-size: 12px; color: #9aa0a6; padding: 4px 14px; min-height: 18px; background: #232428; }
  .frame-wrap { flex: 1; background: #fff; }
  #frame { width: 100%; height: 100%; border: 0; display: block; }
</style>
</head>
<body>
<div class="browser">
  <div class="toolbar">
    <button id="back" class="icon-btn" title="Back">&#8592;</button>
    <button id="fwd" class="icon-btn" title="Forward">&#8594;</button>
    <button id="reload" class="icon-btn" title="Reload">&#8635;</button>
    <button id="home" class="icon-btn" title="Home">&#8962;</button>
    <div class="url-row">
      <input id="url-bar" type="text" spellcheck="false" autocomplete="off" placeholder="Type a URL...">
      <button id="go" type="button" class="icon-btn">Go</button>
    </div>
  </div>
  <div id="status"></div>
  <div class="frame-wrap"><iframe id="frame" title="Mini Browser Frame"></iframe></div>
</div>
<script>
(function(){
  var HOME = "__HOME_URL__";
  var frame = document.getElementById('frame');
  var urlBar = document.getElementById('url-bar');
  var status = document.getElementById('status');
  var back = document.getElementById('back');
  var fwd = document.getElementById('fwd');
  var reload = document.getElementById('reload');
  var home = document.getElementById('home');
  var go = document.getElementById('go');

  var history = [];
  var index = -1;

  function normalize(raw){
    var t = (raw || '').trim();
    if (!t) return null;
    if (/^https?:\\/\\//i.test(t)) return t;
    if (/^[\\w-]+(\\.[\\w-]+)+/.test(t) && t.indexOf(' ') === -1) return 'https://' + t;
    return 'https://www.google.com/search?q=' + encodeURIComponent(t);
  }

  function proxied(url){ return 'proxy?url=' + encodeURIComponent(url); }

  function updateButtons(){
    back.disabled = index <= 0;
    fwd.disabled = index >= history.length - 1;
  }

  function navigate(url, push){
    urlBar.value = url;
    status.textContent = 'Loading ' + url + '...';
    frame.src = proxied(url);
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
    setTimeout(function(){ frame.src = proxied(cur) + '&_t=' + Date.now(); }, 30);
  });
  home.addEventListener('click', function(){ navigate(HOME); });

  navigate(HOME);
})();
</script>
</body>
</html>
"""
