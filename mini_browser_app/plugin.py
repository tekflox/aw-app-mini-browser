"""Entrypoint referenced by aw-app.json's runtime.entrypoint
("mini_browser_app.plugin:MiniBrowserAppPlugin").

Same Tier-1 inprocess pattern as ``tekflox/aw-app-whiteboard`` /
``aw-app-git`` / ``aw-app-presentations``: a FastAPI sub-app is built by
``routes.py`` and mounted at ``/api/apps/mini-browser`` via
``ctx.routes.register`` (``routes:register`` permission). No own database
table is needed — this app is stateless (no board/document to persist,
just a proxy + a viewer shell).
"""

from __future__ import annotations

import logging

from . import routes as routes_mod

log = logging.getLogger("aw_apps.mini_browser")


class MiniBrowserAppPlugin:
    async def activate(self, ctx) -> None:
        self.ctx = ctx
        home_url = (ctx.config or {}).get("home_url", "https://example.com")
        subapp = routes_mod.build_routes(home_url)
        ctx.routes.register(subapp)
        log.info("aw-app-mini-browser activated")

    async def deactivate(self) -> None:
        log.info("aw-app-mini-browser deactivated")
