"""Raw Chrome DevTools Protocol client for the aw-app-browser container.

Ported from ``tekflox/aw-app-devctl``'s ``devctl_app/cdp.py`` (itself ported
from the monolith's ``src/api/whiteboard_browser.py`` piloted-browser
primitives) — drives the existing ``aw-app-browser`` container over CDP
(``aw-app-browser:9223``) instead of launching its own chromium, so the
browser the user sees (noVNC :7900) and the browser Mini Browser's agent
tools control are the SAME instance devctl also pilots.

No hard dependency on CDP being up: `ensure_browser()` starts the container if
it's stopped, waits for CDP, and creates a page target if none exists — so a
caller can pilot even when the browser isn't active. Uses only stdlib +
`websockets` + the `docker` SDK (both present in the workspace). Chrome's CDP
endpoints reject a non-IP/localhost Host header, so we connect by resolved IP.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import urllib.request

CDP_HOST = "aw-app-browser"
CDP_PORT = 9223
CONTAINER = "aw-app-browser"

# windowsVirtualKeyCode for the handful of named keys we dispatch.
_VK = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8,
       "ArrowUp": 38, "ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39,
       "PageDown": 34, "PageUp": 33}


def _http_json(ip: str, path: str):
    with urllib.request.urlopen(f"http://{ip}:{CDP_PORT}{path}", timeout=5) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def _start_container() -> None:
    """Best-effort: start the aw-app-browser container if it's stopped.

    The workspace process reaches the host's rootless podman over the Docker
    API (same mechanism the runtime's ContainerSupervisor uses). If the SDK or
    socket isn't available, do nothing — the CDP poll will just time out with a
    clear error.
    """
    try:
        import docker
    except Exception:
        return
    sock = os.environ.get("DOCKER_HOST") or os.environ.get("AW_PODMAN_SOCKET")
    try:
        if sock:
            base = sock if "://" in sock else "unix://" + sock
            client = docker.DockerClient(base_url=base)
        else:
            client = docker.from_env()
        c = client.containers.get(CONTAINER)
        if c.status != "running":
            c.start()
    except Exception:
        pass


class CDPClient:
    """One lazily-(re)connected CDP websocket to the browser's page target.

    Command/response are matched by id; unsolicited events (e.g.
    `Page.screencastFrame`) are pushed onto `events` for the live-view WS.
    """

    def __init__(self) -> None:
        self._ws = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self.events: asyncio.Queue = asyncio.Queue(maxsize=4)

    async def ensure_browser(self, timeout: float = 30.0) -> str:
        """Guarantee a reachable CDP page target — starting the container and
        creating a page if needed — and return its websocket URL. Does NOT
        depend on the browser already being active."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        started = False
        while True:
            try:
                ip = await loop.run_in_executor(None, socket.gethostbyname, CDP_HOST)
                targets = await loop.run_in_executor(None, _http_json, ip, "/json")
                pages = [t for t in targets if t.get("type") == "page"]
                if not pages:
                    await loop.run_in_executor(None, _http_json, ip, "/json/new?about:blank")
                    await asyncio.sleep(0.4)
                    continue
                tail = pages[0]["webSocketDebuggerUrl"].split(str(CDP_PORT), 1)[1]
                return f"ws://{ip}:{CDP_PORT}{tail}"
            except Exception:
                if not started:
                    await loop.run_in_executor(None, _start_container)
                    started = True
                if loop.time() >= deadline:
                    raise RuntimeError(
                        "aw-app-browser not reachable over CDP (:9223) and could "
                        "not be started")
                await asyncio.sleep(1.0)

    async def _ensure(self) -> None:
        if self._ws is not None:
            return
        import websockets

        uri = await self.ensure_browser()
        self._ws = await websockets.connect(uri, max_size=None, ping_interval=None)
        self._pending = {}
        self.events = asyncio.Queue(maxsize=4)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(msg)
                elif msg.get("method"):
                    if self.events.full():
                        try:
                            self.events.get_nowait()
                        except Exception:
                            pass
                    self.events.put_nowait(msg)
        except Exception:
            pass
        finally:
            self._ws = None  # force reconnect next send

    async def send(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        import websockets

        last_exc: Exception | None = None
        for attempt in (1, 2):  # one reconnect retry
            try:
                await self._ensure()
                self._id += 1
                mid = self._id
                fut: asyncio.Future = asyncio.get_event_loop().create_future()
                self._pending[mid] = fut
                await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                msg = await asyncio.wait_for(fut, timeout=timeout)
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})
            except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
                last_exc = exc
                self._ws = None
        raise last_exc or RuntimeError("cdp send failed")

    # ── piloted-browser primitives (ported) ──────────────────────────────
    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})

    async def screenshot(self, fmt: str = "png") -> bytes:
        r = await self.send("Page.captureScreenshot", {"format": fmt})
        return base64.b64decode(r["data"])

    async def evaluate(self, expression: str):
        r = await self.send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text", "eval error"))
        return r.get("result", {}).get("value")

    async def inject(self, script: str) -> None:
        """Inject a script that runs on this + every future document load."""
        await self.send("Page.addScriptToEvaluateOnNewDocument", {"source": script})
        await self.evaluate(script)

    async def click(self, x: float, y: float, double: bool = False) -> None:
        cc = 2 if double else 1
        for t in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {
                "type": t, "x": x, "y": y, "button": "left", "clickCount": cc,
            })

    async def type_text(self, text: str) -> None:
        await self.send("Input.insertText", {"text": text})

    async def key(self, key: str) -> None:
        vk = _VK.get(key, 0)
        common = {"key": key, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        await self.send("Input.dispatchKeyEvent", {"type": "keyDown", **common})
        await self.send("Input.dispatchKeyEvent", {"type": "keyUp", **common})

    async def scroll(self, dy: int, x: float = 640, y: float = 400) -> None:
        await self.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy,
        })

    async def current(self) -> dict:
        title = await self.evaluate("document.title")
        url = await self.evaluate("location.href")
        return {"title": title, "url": url}


# Module-level singleton — one shared piloted browser per workspace process.
client = CDPClient()
