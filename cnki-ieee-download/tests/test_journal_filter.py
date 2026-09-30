from urllib.parse import parse_qs, urlparse

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
