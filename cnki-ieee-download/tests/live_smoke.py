"""Live smoke test against the real IEEE / ScienceDirect / CNKI sites.

Uses the browser this tool normally launches (~/.carsi_chrome_profile); log in there
for the download checks. Run from cnki-ieee-download/:

    python tests/live_smoke.py                     # all three databases
    python tests/live_smoke.py cnki --caj          # one database; --caj also downloads a CAJ
    python tests/live_smoke.py sciencedirect --sd-downloads=3 [--sd-page=2]

Checks content, not just presence: years, author separators, DOI, year and journal
filters, searches without results, call timings, and that a tab the user has open is left alone. Prints every tool
response and a PASS/FAIL summary. Downloads go to ./downloads/.
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

MAX_SECONDS = 12   # search / detail calls slower than this fail the check
USER_TAB_URL = "https://ieeexplore.ieee.org/Xplore/home.jsp"


async def call(name: str, **args) -> str:
    text = (await server.call_tool(name, args))[0].text
    print(f"\n===== {name} {args}\n{text}", flush=True)
    return text


def seconds(text: str) -> float:
    m = re.search(r"⏱ ([\d.]+)s", text)
    return float(m.group(1)) if m else 0.0


def urls(text: str) -> list[str]:
    return re.findall(r"URL: (\S+)", text)


def results(text: str) -> list[str]:
    """Result blocks of an IEEE/SD search response."""
    return [b for b in text.split("\n\n") if re.match(r"\d+\. \*\*", b.strip())]


def expect(cond, msg: str):
    if not cond:
        raise AssertionError(msg)


def fast(text: str, what: str):
    expect(seconds(text) <= MAX_SECONDS, f"{what} took {seconds(text):.1f}s (> {MAX_SECONDS}s)")


def logged_in(login_text: str) -> bool:
    if "✅" in login_text:
        return True
    print("!! 未登录，跳过下载检查", flush=True)
    return False


def years_within(text: str, lo: int, hi: int) -> bool:
    years = [int(y) for y in re.findall(r"   Year: (\d{4})", text)]
    return bool(years) and all(lo <= y <= hi for y in years)


def from_journal(text: str, journal: str) -> bool:
    """Every result comes from a publication whose title contains journal."""
    sources = re.findall(r"   Source: (.*)", text)
    return bool(sources) and all(journal.lower() in s.lower() for s in sources)


async def check_ieee(opts):
    login = await call("ieee_login")
    q = "radar signal processing"
    p1 = await call("ieee_search", query=q)
    fast(p1, "IEEE search")
    p2 = await call("ieee_search", query=q, page=2)
    expect(urls(p1) and urls(p2) and urls(p1)[0] != urls(p2)[0], "IEEE page 2 repeated page 1")
    blocks = results(p1)
    expect(all(re.search(r"   Year: \d{4}", b) and "   Source: " in b for b in blocks),
           "IEEE results missing year or source")
    filtered = await call("ieee_search", query=q, year_start="2020", year_end="2022")
    expect(years_within(filtered, 2020, 2022), "IEEE year filter not applied")
    journal = "IEEE Transactions on Signal Processing"
    expect(from_journal(await call("ieee_search", query=q, journal=journal), journal),
           "IEEE journal filter not applied")
    detail = await call("ieee_detail", url=urls(p1)[0])
    fast(detail, "IEEE detail")
    expect("**DOI**: 10." in detail and "DOI: DOI" not in detail and "All Authors" not in detail,
           "IEEE detail DOI/authors not clean")
    expect("**Publication**: " in detail and "**Year**: " in detail, "IEEE detail missing venue/year")
    expect(not re.search(r"\*\*Abstract\*\*\nAbstract", detail), "IEEE abstract starts with 'Abstract'")
    if logged_in(login):
        expect("Downloaded PDF" in await call("ieee_download", url=urls(p1)[0]), "IEEE download failed")


async def check_sciencedirect(opts):
    login = await call("sciencedirect_login")
    q = "lithium battery degradation"
    p1 = await call("sciencedirect_search", query=q)
    fast(p1, "SD search")
    p2 = await call("sciencedirect_search", query=q, page=2)
    expect(urls(p1) and urls(p2) and urls(p1)[0] != urls(p2)[0], "SD page 2 repeated page 1")
    blocks = results(p1)
    with_year = sum(bool(re.search(r"   Year: \d{4}", b)) for b in blocks)
    with_sep = sum("; " in (re.search(r"   Authors: (.*)", b) or [None, ""])[1] for b in blocks)
    expect(with_year >= 0.9 * len(blocks), f"SD years missing: {with_year}/{len(blocks)}")
    expect(with_sep >= 0.5 * len(blocks), f"SD authors not separated: {with_sep}/{len(blocks)}")
    filtered = await call("sciencedirect_search", query=q, year_start="2020", year_end="2022")
    expect(years_within(filtered, 2020, 2022), "SD year filter not applied")
    journal = "Journal of Power Sources"
    expect(from_journal(await call("sciencedirect_search", query=q, journal=journal), journal),
           "SD journal filter not applied")
    unknown = await call("sciencedirect_search", query=q, journal="Zzqx Nonexistent Journal")
    expect(unknown.startswith("Search failed: ScienceDirect: ") and seconds(unknown) <= MAX_SECONDS,
           "SD did not report an unknown journal quickly")
    nothing = await call("sciencedirect_search", query="zzqxvbnm qwxzkjh plmokn")
    expect(nothing.startswith("No papers found.") and seconds(nothing) <= MAX_SECONDS,
           "SD search without results did not return 'No papers found.' quickly")
    detail = await call("sciencedirect_detail", url=urls(p1)[0])
    fast(detail, "SD detail")
    expect("**Publication**: " in detail and "**Year**: " in detail and "**DOI**: 10." in detail,
           "SD detail missing venue/year/DOI")
    if not logged_in(login):
        return
    n = int(opts.get("sd-downloads") or 1)
    source = p1 if int(opts.get("sd-page") or 1) == 1 else await call(
        "sciencedirect_search", query=q, page=int(opts["sd-page"]))
    targets = [urls(b)[0] for b in results(source) if "PDF: 可下载" in b and urls(b)][:n]
    challenges = ok = 0
    for u in targets:
        dl = await call("sciencedirect_download", url=u)
        challenges += "ACTION_REQUIRED" in dl
        ok += "Downloaded PDF" in dl
    print(f"\n===== SD downloads: papers={len(targets)} downloaded={ok} security-checks={challenges}",
          flush=True)
    expect(ok + challenges == len(targets), "SD download failed without a security check")


async def check_cnki(opts):
    login = await call("cnki_login")
    q = "雷达信号处理"
    p1 = await call("cnki_search", query=q)
    p3 = await call("cnki_search", query=q, page=3)
    expect(urls(p1) and urls(p3), "CNKI search returned no results")
    expect(urls(p1)[0] != urls(p3)[0] and "第 3/" in p3, "CNKI page 3 not reached")
    expect("来源: " in p1 and "期刊: " not in p1, "CNKI source label")
    p12 = await call("cnki_search", query=q, page=12)
    expect("第 12/" in p12, "CNKI page 12 not reached")
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
    expect(not any(re.search(r"\*\*来源\*\*: .* \.\n", d) for d in details), "CNKI source has trailing ' .'")
    if logged_in(login):
        expect("下载成功" in await call("cnki_download", url=targets[0]), "CNKI download failed")
        if opts.get("caj"):
            orig = server._CNKI_DOWNLOAD_LINKS
            server._CNKI_DOWNLOAD_LINKS = tuple(reversed(orig))   # prefer CAJ for this check only
            try:
                caj = await call("cnki_download", url=targets[1])
            finally:
                server._CNKI_DOWNLOAD_LINKS = orig
            expect("CAJ 下载成功" in caj, "CNKI CAJ download failed")


CHECKS = {"ieee": check_ieee, "sciencedirect": check_sciencedirect, "cnki": check_cnki}


async def main(argv) -> bool:
    opts = {a[2:].split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else True)
            for a in argv if a.startswith("--")}
    targets = [a for a in argv if not a.startswith("--")] or list(CHECKS)

    # A tab "the user" has open on IEEE; the tool must leave it alone.
    await server._ensure_connection()
    user_tab = await server._auth.context.new_page()
    await user_tab.goto(USER_TAB_URL, wait_until="domcontentloaded")

    results_by_db = {}
    for t in targets:
        try:
            await CHECKS[t](opts)
            results_by_db[t] = "PASS"
        except AssertionError as e:
            results_by_db[t] = f"FAIL: {e}"
        except Exception as e:
            results_by_db[t] = f"ERROR: {e!r}"
    results_by_db["user tab untouched"] = "PASS" if user_tab.url == USER_TAB_URL else f"FAIL: now {user_tab.url}"
    await user_tab.close()
    await call("status")
    if server._auth:
        await server._auth.stop()   # disconnect only (not logout): keeps the browser and its tabs
    print("\n===== SUMMARY")
    for t, r in results_by_db.items():
        print(f"{t}: {r}")
    return all(r == "PASS" for r in results_by_db.values())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main(sys.argv[1:])) else 1)
