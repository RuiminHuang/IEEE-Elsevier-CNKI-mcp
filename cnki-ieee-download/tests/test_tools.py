import pytest

import server

pytestmark = pytest.mark.anyio
NO_LOGIN = ["ieee_search", "ieee_detail", "sciencedirect_search", "sciencedirect_detail", "cnki_search", "cnki_detail"]
NEEDS_LOGIN = ["ieee_download", "sciencedirect_download", "cnki_download"]


async def test_descriptions_match_login_behavior():
    tools = {t.name: t.description for t in await server.list_tools()}
    for name in NO_LOGIN:
        assert "Requires prior login" not in tools[name] and "No login needed" in tools[name], name
    for name in NEEDS_LOGIN:
        assert "login" in tools[name].lower(), name
