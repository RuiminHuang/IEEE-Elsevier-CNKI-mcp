import pytest

from carsi_search.databases.cnki import build_pro_query


def test_single_term_is_quoted():
    assert build_pro_query("MIMO 雷达") == "SU='MIMO 雷达'"


def test_all_filters():
    assert build_pro_query("深度学习", author="张三", journal="信号处理",
                           year_start="2020", year_end="2025") == \
        "SU='深度学习' AND AU='张三' AND LY='信号处理' AND YE BETWEEN ('2020','2025')"


def test_quotes_removed_from_values():
    assert build_pro_query("O'Brien model") == "SU='OBrien model'"


def test_years_keep_digits_only_and_accept_ints():
    assert build_pro_query("x", year_start="2020年", year_end=2023) == "SU='x' AND YE BETWEEN ('2020','2023')"


def test_open_ended_year_range():
    assert build_pro_query("x", year_start="2020").startswith("SU='x' AND YE BETWEEN ('2020','")


@pytest.mark.anyio
async def test_pro_search_submits_quoted_query(srv, sites):
    sites.cnki_delay_ms = 200
    text = (await srv.call_tool("cnki_search", {"query": "MIMO 雷达", "author": "张三"}))[0].text
    assert "SU='MIMO 雷达' AND AU='张三'" in text, text
