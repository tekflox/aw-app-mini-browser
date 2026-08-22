// Injected into every proxied page (via uv.config.js's `inject` hook).
// Hooks console.log/warn/error and relays each call to the service worker,
// which broadcasts it on to the toolbar page's dev panel. Best-effort only
// — if there's no controlling service worker yet (first navigation before
// the SW claims the page), calls are silently dropped rather than thrown.
(function () {
    function relay(level, args) {
        try {
            if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
            var safeArgs = [];
            for (var i = 0; i < args.length; i++) {
                var a = args[i];
                try {
                    safeArgs.push(typeof a === 'object' ? JSON.stringify(a) : String(a));
                } catch (e) {
                    safeArgs.push('[unserializable]');
                }
            }
            navigator.serviceWorker.controller.postMessage({
                type: 'uv-console',
                level: level,
                args: safeArgs,
                url: location.href,
            });
        } catch (e) { /* best-effort */ }
    }

    ['log', 'warn', 'error'].forEach(function (level) {
        var original = console[level];
        console[level] = function () {
            relay(level, arguments);
            return original.apply(console, arguments);
        };
    });
})();
