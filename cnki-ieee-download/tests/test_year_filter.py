import re

import pytest

import server
from carsi_search.databases.ieee import IeeeAdapter
from carsi_search.databases.sciencedirect import ScienceDirectAdapter


def test_ieee_url_has_year_range():
    assert "ranges=2020_2022_Year" in IeeeAdapter.build_search_url("x", 1, "2020", "2022")
    assert "ranges" not in IeeeAdapter.build_search_url("x", 1)


def test_sd_url_has_date_range():
    assert "date=2020-2022" in ScienceDirectAdapter.build_search_url("x", 1, "2020年", 2022)
    assert "date=" not in ScienceDirectAdapter.build_search_url("x", 1)


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["ieee_search", "sciencedirect_search"])
async def test_results_are_within_years(srv, sites, tool):
    text = (await srv.call_tool(tool, {"query": "radar", "year_start": "2020", "year_end": "2022"}))[0].text
    years = [int(y) for y in re.findall(r"   Year: (\d{4})", text)]
    assert years and all(2020 <= y <= 2022 for y in years), text
    assert "[年份=2020-2022]" in text, text


@pytest.mark.anyio
async def test_search_schemas_accept_years():
    tools = {t.name: t for t in await server.list_tools()}
    for name in ("ieee_search", "sciencedirect_search"):
        assert {"year_start", "year_end"} <= set(tools[name].input_schema["properties"]), name
