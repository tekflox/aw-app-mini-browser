"""Borrowed-cookie bridge — the gate, the merge, and the fail-open promise.

The gate tests are the ones that matter most: this feature attaches real
logged-in sessions to outbound requests, so "off by default" and "only the
hosts you named" have to be provable, not just intended.

Run: python -m pytest tests/test_cookies.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_browser_app.cookies import (  # noqa: E402
    BrowserCookieBridge, host_allowed, merge_cookie_header,
)


# --------------------------------------------------------------------------
# host gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("host,allowlist,expected", [
    ("google.com", ["google.com"], True),
    ("mail.google.com", ["google.com"], True),      # subdomains covered
    ("mail.google.com", [".google.com"], True),     # leading dot tolerated
    ("notgoogle.com", ["google.com"], False),       # suffix, not substring
    ("google.com.evil.test", ["google.com"], False),
    ("google.com", [], False),                      # empty = share nothing
    ("", ["google.com"], False),
])
def test_host_allowed(host, allowlist, expected):
    assert host_allowed(host, allowlist) is expected


@pytest.mark.asyncio
async def test_disabled_bridge_never_calls_out(monkeypatch):
    bridge = BrowserCookieBridge(enabled=False, hosts=["google.com"])

    async def _boom(*_a, **_kw):
        raise AssertionError("called the proxy while the feature was off")

    monkeypatch.setattr(bridge._client, "get", _boom)
    assert await bridge.cookies_for("https://mail.google.com/", "mail.google.com") == []


@pytest.mark.asyncio
async def test_host_outside_allowlist_never_calls_out(monkeypatch):
    bridge = BrowserCookieBridge(enabled=True, hosts=["google.com"])

    async def _boom(*_a, **_kw):
        raise AssertionError("called the proxy for a host outside the allowlist")

    monkeypatch.setattr(bridge._client, "get", _boom)
    assert await bridge.cookies_for("https://evil.test/", "evil.test") == []


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------

def test_merge_appends_to_an_existing_header():
    merged = merge_cookie_header("a=1", [{"name": "SID", "value": "x"}])
    assert merged == "a=1; SID=x"


def test_merge_never_overrides_ultraviolets_own_jar():
    """A session created inside Mini Browser wins over a stale one from the
    container's profile — it's the one the user is looking at."""
    merged = merge_cookie_header("SID=mine", [{"name": "SID", "value": "theirs"}])
    assert merged == "SID=mine"


def test_merge_into_an_empty_header():
    assert merge_cookie_header("", [{"name": "SID", "value": "x"}]) == "SID=x"


def test_merge_with_nothing_to_add_is_a_noop():
    assert merge_cookie_header("a=1", []) == "a=1"


def test_merge_handles_spacing_and_valueless_pairs():
    merged = merge_cookie_header(" a=1 ; flag ; b=2 ",
                                 [{"name": "flag", "value": "z"},
                                  {"name": "c", "value": "3"}])
    assert merged.endswith("; c=3")
    assert "flag=z" not in merged     # 'flag' was already present


# --------------------------------------------------------------------------
# fail-open + cache
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proxy_unreachable_yields_no_cookies(monkeypatch):
    """A page that would have loaded logged-out before must still load."""
    bridge = BrowserCookieBridge(enabled=True, hosts=["google.com"])

    async def _explode(*_a, **_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(bridge._client, "get", _explode)
    assert await bridge.cookies_for("https://mail.google.com/", "mail.google.com") == []


@pytest.mark.asyncio
async def test_proxy_error_status_yields_no_cookies(monkeypatch):
    bridge = BrowserCookieBridge(enabled=True, hosts=["google.com"])
    monkeypatch.setattr(bridge._client, "get", _fake_get(404, {}))
    assert await bridge.cookies_for("https://mail.google.com/", "mail.google.com") == []


@pytest.mark.asyncio
async def test_second_request_for_the_same_url_is_served_from_cache(monkeypatch):
    bridge = BrowserCookieBridge(enabled=True, hosts=["google.com"])
    calls = []
    monkeypatch.setattr(bridge._client, "get", _fake_get(
        200, {"cookies": [{"name": "SID", "value": "x"}]}, calls))

    first = await bridge.cookies_for("https://mail.google.com/a?q=1", "mail.google.com")
    second = await bridge.cookies_for("https://mail.google.com/a?q=2", "mail.google.com")

    assert first == second == [{"name": "SID", "value": "x"}]
    # Query string is not part of cookie matching, so both hit one entry.
    assert len(calls) == 1
    assert calls[0]["params"] == {"url": "https://mail.google.com/a"}


def _fake_get(status, payload, calls=None):
    async def _get(url, params=None, **_kw):
        if calls is not None:
            calls.append({"url": url, "params": params})
        return _FakeResponse(status, payload)
    return _get


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload
