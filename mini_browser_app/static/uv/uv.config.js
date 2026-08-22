/*global Ultraviolet*/
// mini-browser's own config — NOT the stock uv.config.js. Paths point at
// this app's own route prefix; `inject` wires the dev-panel hooks (console
// capture) into every proxied page. See mini_browser_app/routes.py for the
// Bare Server v3 backend this ultimately talks to.
self.__uv$config = {
    prefix: '/api/apps/mini-browser/uv/service/',
    encodeUrl: Ultraviolet.codec.xor.encode,
    decodeUrl: Ultraviolet.codec.xor.decode,
    handler: '/api/apps/mini-browser/uv/uv.handler.js',
    client: '/api/apps/mini-browser/uv/uv.client.js',
    bundle: '/api/apps/mini-browser/uv/uv.bundle.js',
    config: '/api/apps/mini-browser/uv/uv.config.js',
    sw: '/api/apps/mini-browser/uv/uv.sw.js',
    // Inlined, not `<script src>` — a path-absolute src resolves against
    // the PROXIED page's own (rewritten) origin, e.g. google.com, not
    // ours, and 404s there (confirmed live). Keep this in sync with
    // devpanel-inject.js by hand; there's no build step to do it for us.
    inject: [{
        host: '.*',
        injectTo: 'head',
        html: '<script>(function(){function relay(level,args){try{if(!navigator.serviceWorker||!navigator.serviceWorker.controller)return;var safeArgs=[];for(var i=0;i<args.length;i++){var a=args[i];try{safeArgs.push(typeof a==="object"?JSON.stringify(a):String(a));}catch(e){safeArgs.push("[unserializable]");}}navigator.serviceWorker.controller.postMessage({type:"uv-console",level:level,args:safeArgs,url:location.href});}catch(e){}}["log","warn","error"].forEach(function(level){var original=console[level];console[level]=function(){relay(level,arguments);return original.apply(console,arguments);};});})();</script>',
    }],
};
