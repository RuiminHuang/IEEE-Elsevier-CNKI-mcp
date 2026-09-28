"""Shared fixtures: a headless browser reached over CDP (as in production),
fake IEEE / ScienceDirect / CNKI sites, and a local download server."""

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from carsi_search import engine  # noqa: E402

import fake_sites  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CdpBrowser:
    """Headless Chromium/Edge with remote debugging, like the one CarsiAuth launches."""

    def __init__(self, exe: str, base: Path):
        self.exe, self.base = exe, base
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.runs = 0

    def start(self) -> subprocess.Popen:
        self.runs += 1   # fresh profile per run: a killed browser can leave its profile locked
        # --no-sandbox: Playwright's Chromium exits at once (code 3) here without it;
        # the test browser only ever loads local fake pages.
        self.proc = subprocess.Popen(
            [self.exe, "--headless=new", "--no-sandbox", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.base / f'profile{self.runs}'}",
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with no_proxy.open(self.url + "/json/version", timeout=1):
                    return self.proc
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("test browser did not start")

    def kill(self):
        if self.running():
            self.proc.kill()
            self.proc.wait(10)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


@pytest.fixture(scope="session")
def browser_exe() -> str:
    env = os.environ.get("TEST_BROWSER_PATH")
    if env:
        return env
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        path = p.chromium.executable_path
    if Path(path).exists():
        return path
    found = engine._find_browser()
    if not found:
        pytest.skip("no Chromium/Edge available for tests")
    return found


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def cdp_browser(browser_exe, tmp_path, monkeypatch):
    """Point engine at a fresh headless browser; isolate profile, state file and cwd.
    If CarsiAuth needs to (re)launch the browser, it relaunches this headless one."""
    b = CdpBrowser(browser_exe, tmp_path)
    monkeypatch.setattr(engine, "CDP_URL", b.url)
    monkeypatch.setattr(engine, "_CDP_PROFILE", tmp_path / "carsi_profile")
    monkeypatch.setattr(engine.CarsiAuth, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.chdir(tmp_path)

    async def launch(self):
        self._browser_process = b.start()

    monkeypatch.setattr(engine.CarsiAuth, "_launch_browser", launch)
    b.start()
    yield b
    b.kill()


@pytest.fixture
async def srv(cdp_browser):
    """The server module with clean global state; disconnects Playwright afterwards."""
    server._auth, server._pages = None, {}
    yield server
    if server._auth:
        try:
            await server._auth.stop()
        except Exception:
            pass
    server._auth, server._pages = None, {}


@pytest.fixture
def sites(cdp_browser, monkeypatch):
    """Serve the fake sites on every connection CarsiAuth makes (reconnects included)."""
    state = fake_sites.FakeState()
    orig_start = engine.CarsiAuth.start

    async def start(self):
        await orig_start(self)
        state.connections += 1
        await fake_sites.install(self.context, state)
        return self

    monkeypatch.setattr(engine.CarsiAuth, "start", start)
    return state


@pytest.fixture
def http_site():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), fake_sites.DownloadHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
