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
    inject: [{
        host: '.*',
        injectTo: 'head',
        html: '<script src="/api/apps/mini-browser/uv/devpanel-inject.js"></script>',
    }],
};
