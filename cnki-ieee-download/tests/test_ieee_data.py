import json
from pathlib import Path

import pytest

from carsi_search.databases.ieee import parse_metadata, parse_search_record

FIX = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIX / "ieee_search.json").read_text(encoding="utf-8"))
META = json.loads((FIX / "ieee_metadata.json").read_text(encoding="utf-8"))


def test_search_record_fields():
    rec = SEARCH["records"][0]
    p = parse_search_record(rec)
    assert p["authors"] == "; ".join(a["preferredName"] for a in rec["authors"])
    assert p["year"] == rec["publicationYear"] and len(p["year"]) == 4
    # highlight markers like "[::Signal::]" are stripped
    assert p["source"] == "2022 14th International Conference on Signal Processing Systems (ICSPS)"
    assert "[::" not in p["title"] + p["abstract"]
    assert p["url"] == f"https://ieeexplore.ieee.org/document/{rec['articleNumber']}/"


def test_metadata_fields():
    d = parse_metadata(META)
    assert d["authors"] == [a["name"] for a in META["authors"]]
    assert d["doi"] == "10.1109/ICSPS58776.2022.00106"
    assert d["venue"] == META["publicationTitle"] and d["year"] == "2022"
    assert d["pages"] == "573-578"
    assert not d["abstract"].lower().startswith("abstract")
    assert d["pdfUrl"] == "https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=10218450"
    # author and IEEE keywords kept; the long machine-generated "Index Terms" list is not
    assert "FPGA" in d["keywords"] and "Phased arrays" in d["keywords"]
    assert "Development Cycle" not in d["keywords"]


@pytest.mark.anyio
async def test_ieee_search_output_has_year_and_source(srv, sites):
    text = (await srv.call_tool("ieee_search", {"query": "radar"}))[0].text
    assert text.count("   Year: ") == 3 and text.count("   Source: ") == 3, text
    assert "Authors: Ziye Wang; Renhong Xie" in text, text


@pytest.mark.anyio
async def test_ieee_detail_output_is_clean(srv, sites):
    text = (await srv.call_tool("ieee_detail", {"url": "https://ieeexplore.ieee.org/document/1001/"}))[0].text
    assert "**IEEE Doc 1001**" in text and "**Year**: 2022" in text, text
    assert "**Publication**: 2022 14th International Conference" in text, text
    assert "**DOI**: 10.1109/" in text and "DOI: DOI" not in text and "All Authors" not in text, text
