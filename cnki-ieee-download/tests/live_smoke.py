"""Live smoke test against the real IEEE / ScienceDirect / CNKI sites.

Uses the browser this tool normally launches (~/.carsi_chrome_profile); log in there
for the download checks. Run from cnki-ieee-download/:

    python tests/live_smoke.py                       # all three databases
    python tests/live_smoke.py cnki                  # one database
    python tests/live_smoke.py cnki --caj-url=<detail URL of a CAJ-only paper>

Prints every tool response and a PASS/FAIL summary. Downloads go to ./downloads/.
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


async def call(name: str, **args) -> str:
    text = (await server.call_tool(name, args))[0].text
    print(f"\n===== {name} {args}\n{text}", flush=True)
    return text


def urls(text: str) -> list[str]:
    return re.findall(r"URL: (\S+)", text)


def expect(cond, msg: str):
    if not cond:
        raise AssertionError(msg)


def logged_in(login_text: str) -> bool:
    if "✅" in login_text:
        return True
    print("!! 未登录，跳过下载检查", flush=True)
    return False


async def check_ieee(opts):
    login = await call("ieee_login")
    q = "radar signal processing"
    p1 = await call("ieee_search", query=q)
    p2 = await call("ieee_search", query=q, page=2)
    expect(urls(p1) and urls(p2), "IEEE search returned no results")
    expect(urls(p1)[0] != urls(p2)[0], "IEEE page 2 repeated page 1")
    detail = await call("ieee_detail", url=urls(p1)[0])
    expect("**Abstract**" in detail, "IEEE detail has no abstract")
    if logged_in(login):
        expect("Downloaded PDF" in await call("ieee_download", url=urls(p1)[0]), "IEEE download failed")


async def check_sciencedirect(opts):
    login = await call("sciencedirect_login")
    q = "lithium battery degradation"
    p1 = await call("sciencedirect_search", query=q)
    p2 = await call("sciencedirect_search", query=q, page=2)
    expect(urls(p1) and urls(p2), "ScienceDirect search returned no results")
    expect(urls(p1)[0] != urls(p2)[0], "ScienceDirect page 2 repeated page 1")
    expect("PDF: " in p1, "ScienceDirect results lack the PDF marker")
    detail = await call("sciencedirect_detail", url=urls(p1)[0])
    expect("**Abstract**" in detail, "ScienceDirect detail has no abstract")
    if logged_in(login):
        dl = await call("sciencedirect_download", url=urls(p1)[0])
        expect("Downloaded PDF" in dl or "ACTION_REQUIRED" in dl, "ScienceDirect download failed")


async def check_cnki(opts):
    login = await call("cnki_login")
    q = "雷达信号处理"
    p1 = await call("cnki_search", query=q)
    p3 = await call("cnki_search", query=q, page=3)
    expect(urls(p1) and urls(p3), "CNKI search returned no results")
    expect(urls(p1)[0] != urls(p3)[0] and "第 3/" in p3, "CNKI page 3 not reached")
    by_date = await call("cnki_search", query=q, sort="date")
    dates = re.findall(r"日期: (\d{4}-\d{2}-\d{2})", by_date)
    expect(dates and dates == sorted(dates, reverse=True), f"CNKI sort by date not newest first: {dates[:5]}")
    by_rel = await call("cnki_search", query=q, sort="relevance")
    expect(urls(by_rel) and urls(by_rel)[:5] != urls(by_date)[:5], "CNKI relevance sort not applied")
    pro = await call("cnki_search", query=q, year_start="2022", year_end="2024")
    years = re.findall(r"日期: (\d{4})", pro)
    expect(years and all("2022" <= y <= "2024" for y in years), f"CNKI year filter not applied: {years}")
    targets = urls(p1)[:3]
    details = await asyncio.gather(*(call("cnki_detail", url=u) for u in targets))
    titles = [d.splitlines()[0] for d in details]
    expect(len(set(titles)) == len(titles) and all(t.startswith("**") for t in titles),
           f"parallel CNKI details mixed up: {titles}")
    if logged_in(login):
        expect("下载成功" in await call("cnki_download", url=targets[0]), "CNKI download failed")
        if opts.get("caj-url"):
            expect("CAJ 下载成功" in await call("cnki_download", url=opts["caj-url"]), "CNKI CAJ download failed")


CHECKS = {"ieee": check_ieee, "sciencedirect": check_sciencedirect, "cnki": check_cnki}


async def main(argv) -> bool:
    opts = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    targets = [a for a in argv if not a.startswith("--")] or list(CHECKS)
    results = {}
    for t in targets:
        try:
            await CHECKS[t](opts)
            results[t] = "PASS"
        except AssertionError as e:
            results[t] = f"FAIL: {e}"
        except Exception as e:
            results[t] = f"ERROR: {e!r}"
    await call("status")
    if server._auth:
        await server._auth.stop()   # disconnect only (not logout): keeps the browser and saved cookies
    print("\n===== SUMMARY")
    for t, r in results.items():
        print(f"{t}: {r}")
    return all(r == "PASS" for r in results.values())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main(sys.argv[1:])) else 1)
