import pytest

pytestmark = pytest.mark.anyio
ARTICLE = "https://www.sciencedirect.com/science/article/pii/S0000000001"


async def test_sd_search_authors_are_separated_and_years_present(srv, sites):
    text = (await srv.call_tool("sciencedirect_search", {"query": "radar"}))[0].text
    assert "Authors: Alice 1; Bob 1" in text, text
    assert text.count("   Year: ") == 10 and text.count("   Source: Journal X") == 10, text


async def test_sd_extraction_on_real_snapshot(srv, sites):
    # the fake serves the live-captured fixtures/sd_search_items.html for this query
    text = (await srv.call_tool("sciencedirect_search", {"query": "__snapshot__"}))[0].text
    assert "Authors: Weiping Diao; Jonghoon Kim; Michael Pecht" in text, text
    assert "Authors: Maha Yusuf; Jacob M. LaManna; Johanna Nelson Weker" in text, text
    assert "Source: Electrochimica Acta" in text and text.count("   Year: 2022") == 3, text
    assert "(total: 15,460)" in text, text


async def test_sd_detail_fields(srv, sites):
    text = (await srv.call_tool("sciencedirect_detail", {"url": ARTICLE}))[0].text
    assert "**Publication**: Journal X" in text and "**Year**: 2021" in text, text
    assert "**Authors**: Alice Smith, Bob Jones" in text, text          # no affiliation letters
    assert "**DOI**: 10.1016/test.S0000000001" in text, text
    assert "Summary of S0000000001" in text and "Highlight one" not in text, text
    assert "**Keywords**: Batteries, Degradation" in text, text
    assert "S0000000001/pdfft" in text and "SREF000001" not in text, text   # not a reference's PDF
