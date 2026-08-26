"""Borrowed browser cookies — the client half of ``aw-app-proxy``'s
``GET /cookies-for``.

Why this exists: ``/view`` navigates through a vendored Ultraviolet, whose
cookie jar lives in an IndexedDB **inside the user's own browser**, managed
by the service worker. The Chromium in ``aw-app-browser`` has a completely
separate jar (its own container profile, ~170 cookies of real logged-in
sessions). Nothing connected the two, so a site you are signed into in the
Browser window asks you to sign in again in Mini Browser.

Two design choices worth keeping when this changes:

**Server-side, not jar-seeding.** The obvious alternative — push the
container's cookies into Ultraviolet's IndexedDB — would expose every
borrowed cookie to the proxied page's own JS via ``document.cookie``,
including the ~78 that are ``HttpOnly`` precisely so that can't happen.
Injecting into the outbound request headers here instead keeps them
invisible to page script, and keeps this app off Ultraviolet's internals
(which are vendored and meant to be swapped wholesale on upgrade).

**The proxy owns the jar, we only read it.** ``aw-app-proxy`` already
holds the write side (extension sync → ``Network.setCookie``), the Fernet
key and the persistence table. Reading over loopback costs one hop and
keeps one owner, instead of a second CDP cookie implementation here that
would drift from that one. Both apps are Tier-1 in the same process, so
the hop is loopback HTTP — the same pattern ``routes.py`` already uses to
reach ``devctl``'s renderer, and the only app-to-app convention the
framework actually sanctions (``AppContext`` has no app-calling facade).

Off by default (``share_browser_cookies``), and an empty
``cookie_share_hosts`` means share nothing — turning the feature on is not
enough, you also say where. See ``bare_server.py`` for where the merge
happens.
"""

from __future__ import annotations

import os
import time

import httpx

# How long a per-URL cookie set is reused. A page load fans out into dozens
# of subresource requests within a second or two; without this each one
# would be its own CDP round trip through the proxy. Short enough that a
# fresh login in the Browser window shows up on the next navigation.
_TTL_SECONDS = 10.0

# Bounded so a long session can't grow this without limit. Evicts oldest-
# inserted first, which for browsing traffic is close enough to LRU.
_MAX_ENTRIES = 256


def _proxy_base() -> str:
    return f"http://127.0.0.1:{os.environ.get('AW_PORT', '9030')}/api/apps/proxy"


def host_allowed(host: str, allowlist: list[str]) -> bool:
    """Host allowlist, matched like a cookie domain: ``google.com`` covers
    ``mail.google.com``. An empty allowlist allows nothing — the feature
    needs two deliberate acts (turn it on, then say where), because the
    failure mode of a too-wide default here is handing a site someone
    else's logged-in session.
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    for entry in allowlist or []:
        entry = (entry or "").strip().lower().lstrip(".")
        if entry and (host == entry or host.endswith("." + entry)):
            return True
    return False


def merge_cookie_header(existing: str, borrowed: list[dict]) -> str:
    """Append borrowed cookies to whatever Ultraviolet's own jar already
    sent, **without overriding a name it already set**.

    Precedence matters: a session created inside Mini Browser itself is the
    one the user is looking at, so it must survive contact with a stale
    cookie of the same name from the container's profile.
    """
    existing = (existing or "").strip()
    have = set()
    for pair in existing.split(";"):
        name, _, _ = pair.strip().partition("=")
        if name:
            have.add(name)

    additions = [f"{c['name']}={c['value']}" for c in borrowed
                 if c.get("name") and c["name"] not in have]
    if not additions:
        return existing
    return "; ".join(([existing] if existing else []) + additions)


class BrowserCookieBridge:
    """Fetches (and briefly caches) the cookies aw-app-browser would send.

    Fails open, always: any error — proxy not installed, browser stopped,
    malformed reply — yields no cookies and lets the request proceed
    unauthenticated. Borrowing sessions is an enhancement; a page that
    would have loaded logged-out before must still load.
    """

    def __init__(self, enabled: bool, hosts: list[str]) -> None:
        self.enabled = bool(enabled)
        self.hosts = list(hosts or [])
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._client = httpx.AsyncClient(timeout=5.0)

    def _cached(self, key: str) -> list[dict] | None:
        hit = self._cache.get(key)
        if hit and (time.monotonic() - hit[0]) < _TTL_SECONDS:
            return hit[1]
        return None

    def _store(self, key: str, cookies: list[dict]) -> None:
        if len(self._cache) >= _MAX_ENTRIES:
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (time.monotonic(), cookies)

    async def cookies_for(self, url: str, host: str) -> list[dict]:
        if not self.enabled or not host_allowed(host, self.hosts):
            return []
        # Query is not part of cookie matching; dropping it keeps the cache
        # from splitting into one entry per distinct query string.
        key = url.split("?", 1)[0]
        if (hit := self._cached(key)) is not None:
            return hit
        try:
            resp = await self._client.get(f"{_proxy_base()}/cookies-for",
                                          params={"url": key})
            cookies = resp.json().get("cookies", []) if resp.status_code == 200 else []
        except Exception:
            cookies = []
        if not isinstance(cookies, list):
            cookies = []
        self._store(key, cookies)
        return cookies
