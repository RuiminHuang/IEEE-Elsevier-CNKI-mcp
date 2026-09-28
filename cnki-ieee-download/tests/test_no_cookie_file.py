import pytest

from carsi_search import engine


def test_engine_keeps_no_cookie_file():
    assert not hasattr(engine.CarsiAuth, "STATE_FILE")
    assert not hasattr(engine.CarsiAuth, "save_state")


@pytest.mark.anyio
async def test_tool_calls_write_no_cookie_file(srv, sites, tmp_path):
    await srv.call_tool("ieee_login", {})
    await srv.call_tool("ieee_search", {"query": "radar"})
    assert not list(tmp_path.glob("*state*.json"))
