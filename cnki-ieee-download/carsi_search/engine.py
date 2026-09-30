"""
CDP connection manager for a Chrome/Edge browser.

Auto-launches Chrome or Edge with CDP debugging if not already running. Logins
persist in the browser's own profile (~/.carsi_chrome_profile), so the user only
needs to log in once; no cookie file is written.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from playwright.async_api import async_playwright, Browser

# "localhost", not 127.0.0.1: Edge 154 listens on the IPv6 loopback [::1] only.
DEFAULT_CDP_URL = "http://localhost:9222"
CDP_URL = os.environ.get("CHROME_CDP_URL", DEFAULT_CDP_URL)
_CDP_PROFILE = Path.home() / ".carsi_chrome_profile"
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")

LOG_FILE = Path(__file__).parent.parent / "carsi.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("carsi")


def _find_browser() -> str | None:
    """Find Chrome or Edge executable on the system."""
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    if sys.platform == "win32":
        candidates = [
            # Edge (preferred on Windows)
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            # Chrome
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:
        candidates = []

    for p in candidates:
        if Path(p).exists():
            return p

    # Fallback: search PATH
    for name in ["msedge", "microsoft-edge", "chrome", "google-chrome", "chromium"]:
        found = shutil.which(name)
        if found:
            return found

    return None


def _cdp_port() -> str:
    return CDP_URL.split(":")[-1].rstrip("/")


def _is_cdp_available() -> bool:
    """Quick check if CDP port is already listening. Bypasses any system proxy: a local
    port must not depend on a proxy app running (or on it forwarding 127.0.0.1)."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{CDP_URL}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _bypass_proxy_for_loopback():
    """Playwright's driver sends the CDP handshake through HTTP(S)_PROXY, and a proxy app
    can't reach the browser's loopback port (it answers 502). Put loopback in NO_PROXY."""
    for key in ("NO_PROXY", "no_proxy"):   # one variable on Windows, two elsewhere
        hosts = [h.strip() for h in os.environ.get(key, "").split(",") if h.strip()]
        os.environ[key] = ",".join(hosts + [h for h in _LOOPBACK_HOSTS if h not in hosts])


class CarsiAuth:
    """CDP connection wrapper with browser auto-launch."""

    def __init__(self):
        self.browser: Browser | None = None
        self.context = None
        self._playwright = None
        self._browser_process: subprocess.Popen | None = None

    async def start(self):
        if not _is_cdp_available():
            await self._launch_browser()

        _bypass_proxy_for_loopback()   # before the Playwright driver starts: it inherits the env
        self._playwright = await async_playwright().start()
        for attempt in range(3):
            try:
                self.browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
                break
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    await self._playwright.stop()
                    self._playwright = None
                    raise RuntimeError(
                        f"无法连接浏览器 CDP ({CDP_URL})。请手动启动 Chrome/Edge，例如：\n"
                        f'msedge --remote-debugging-port={_cdp_port()} --user-data-dir="{_CDP_PROFILE}"\n'
                        "（新版 Chrome/Edge 必须同时指定 --user-data-dir，否则调试端口不会打开）"
                    )

        if not self.browser:
            raise RuntimeError("浏览器连接失败")

        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        log.info(f"[CDP] 已连接浏览器: {CDP_URL}")
        return self

    async def _launch_browser(self):
        browser_path = _find_browser()
        if not browser_path:
            raise RuntimeError(
                "找不到 Chrome/Edge 浏览器。请安装 Chrome 或 Edge，或设置 CHROME_PATH 环境变量。"
            )

        browser_name = "Edge" if "edge" in browser_path.lower() else "Chrome"
        log.info(f"[CDP] 自动启动 {browser_name}...")
        _CDP_PROFILE.mkdir(parents=True, exist_ok=True)

        port = _cdp_port()
        cmd = [
            browser_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={_CDP_PROFILE}",
        ]

        try:
            self._browser_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info(f"[CDP] {browser_name} 已启动 (PID={self._browser_process.pid})")
            await asyncio.sleep(2)
        except Exception as e:
            raise RuntimeError(f"启动 {browser_name} 失败: {e}")

    def is_alive(self) -> bool:
        """True while the CDP connection to the browser is still open."""
        return self.browser is not None and self.browser.is_connected() and self.context is not None

    async def stop(self):
        """Disconnect from the browser. The browser keeps running so logins survive."""
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                log.debug(f"[CDP] playwright stop error: {e}")
            self._playwright = None
        self.browser = None
        self.context = None
