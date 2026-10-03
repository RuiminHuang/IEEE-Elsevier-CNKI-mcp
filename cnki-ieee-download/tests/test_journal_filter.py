import re
from urllib.parse import parse_qs, urlparse

import pytest

import server
from carsi_search.databases.base import normalize_journal
from carsi_search.databases.ieee import IeeeAdapter
from carsi_search.databases.sciencedirect import ScienceDirectAdapter

TSP = "IEEE Transactions on Signal Processing"


def params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_normalize_journal():
    assert normalize_journal('  "IEEE  Transactions on Signal\nProcessing" ') == TSP
    assert normalize_journal("“Radar”  Letters") == "Radar Letters"
    assert normalize_journal(None) == "" and normalize_journal(' "" ') == ""


def test_ieee_query_gets_publication_title_clause():
    assert params(IeeeAdapter.build_search_url("radar", 1, journal=TSP))["queryText"] == \
        f'(radar) AND ("Publication Title":"{TSP}")'
    assert params(IeeeAdapter.build_search_url("radar", 1))["queryText"] == "radar"
    assert params(IeeeAdapter.build_search_url("radar", 1, journal="  "))["queryText"] == "radar"


def test_sd_url_has_pub():
    url = ScienceDirectAdapter.build_search_url("x", 2, "2020", "2022", journal=" Journal of  Power Sources ")
    assert params(url)["pub"] == "Journal of Power Sources"
    assert params(url)["offset"] == "25" and params(url)["date"] == "2020-2022"
    assert "pub" not in params(ScienceDirectAdapter.build_search_url("x", 1))
    assert "pub" not in params(ScienceDirectAdapter.build_search_url("x", 1, journal=""))


JOURNALS = {"ieee_search": TSP, "sciencedirect_search": "Journal of Power Sources"}


@pytest.mark.anyio
@pytest.mark.parametrize("tool", list(JOURNALS))
async def test_results_come_from_journal(srv, sites, tool):
    journal = JOURNALS[tool]
    text = (await srv.call_tool(tool, {"query": "radar", "journal": journal}))[0].text
    sources = re.findall(r"   Source: (.*)", text)
    assert sources and all(s == journal for s in sources), text
    assert f"[期刊={journal}]" in text, text


@pytest.mark.anyio
@pytest.mark.parametrize("tool", list(JOURNALS))
async def test_journal_combines_with_years(srv, sites, tool):
    journal = JOURNALS[tool]
    text = (await srv.call_tool(tool, {"query": "radar", "journal": journal,
                                       "year_start": "2020", "year_end": "2022"}))[0].text
    years = [int(y) for y in re.findall(r"   Year: (\d{4})", text)]
    assert years and all(2020 <= y <= 2022 for y in years), text
    assert f"[期刊={journal}, 年份=2020-2022]" in text, text


@pytest.mark.anyio
async def test_search_schemas_accept_journal():
    tools = {t.name: t for t in await server.list_tools()}
    for name in JOURNALS:
        assert "journal" in tools[name].input_schema["properties"], name
