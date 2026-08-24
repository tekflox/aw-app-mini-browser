// Integrated-mode entrypoint — dynamic-imported by aw-workspace-ui's
// loadComponentPlugin() once this app is installed with "ui:code" granted.
// Built by `npm run build` -> ui/dist/mini-browser.js, referenced from
// aw-app.json's contributes.frontend.bundle.
//
// Deliberately narrow: registers ONLY the window's title-bar pop-out action
// (core.window.titlebar:mini-browser.main via host.registerWindowActions).
// The window BODY stays untouched — aw-app.json's windows[0].body.type is
// still "declarative" (windows/main.json -> the /view iframe, all of it
// server-rendered by viewer.py's proxy/dev-panel JS). BasicWindow.jsx renders
// the title-bar slot unconditionally regardless of body.type (see
// aw-workspace-ui's slotRegistry.js), so a component-mode frontend
// contribution and a declarative body coexist on the same window — no need
// to port the whole browser UI into a React component just for one button.
//
// Was an in-page toolbar button inside viewer.py's own HTML first (an "open
// externally" icon next to Go) — replaced by this because it looked and
// behaved nothing like every other window's native pop-out action (Terminal,
// Whiteboard): different position, different icon, no host-chrome
// integration. This is the same "Pop out to new window" pattern and icon as
// aw-workspace-ui's TerminalWindow.jsx and aw-app-whiteboard's
// WhiteboardWindowActions.

export function register(host) {
  function MiniBrowserWindowActions() {
    const viewUrl = host.app.absoluteApiUrl('/view');
    return (
      <button
        onClick={() => window.open(viewUrl, 'mini-browser-main', 'popup=1,width=1200,height=800')}
        className="p-1 rounded hover:bg-white/10 text-[var(--color-text-muted)]"
        title="Pop out to new window"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
          <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      </button>
    );
  }

  host.registerWindowActions('mini-browser.main', MiniBrowserWindowActions);
}

export default register;
