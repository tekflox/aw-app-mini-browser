/*global UVServiceWorker,__uv$config*/
// mini-browser's own service worker entry — NOT Ultraviolet's stock sw.js.
// Same importScripts sequence as the stock file, plus dev-panel event
// relay: every proxied request/response gets broadcast to every open
// client (the toolbar page's dev panel listens via
// navigator.serviceWorker.addEventListener('message', ...)).
importScripts('uv.bundle.js');
importScripts('uv.config.js');
importScripts(__uv$config.sw || 'uv.sw.js');

const uv = new UVServiceWorker();

function broadcast(msg) {
    self.clients.matchAll({ includeUncontrolled: true }).then((list) => {
        for (const c of list) c.postMessage(msg);
    });
}

uv.on('request', (event) => {
    const d = event.data || {};
    broadcast({ type: 'uv-request', method: d.method, url: d.url ? String(d.url) : null });
});

uv.on('response', (event) => {
    const d = event.data || {};
    broadcast({
        type: 'uv-response',
        url: d.request && d.request.url ? String(d.request.url) : null,
        status: d.status,
        statusText: d.statusText,
    });
});

// Relays console.* calls forwarded by devpanel-inject.js (running inside
// each proxied page) up to the dev panel — the SW is the only thing both
// the proxied iframe and the toolbar page can both reach.
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'uv-console') broadcast(event.data);
});

async function handleRequest(event) {
    if (uv.route(event)) return await uv.fetch(event);
    return await fetch(event.request);
}

self.addEventListener('fetch', (event) => {
    event.respondWith(handleRequest(event));
});
