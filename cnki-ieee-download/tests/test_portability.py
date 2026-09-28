import server
from carsi_search import registry
from carsi_search.databases.cnki import CnkiAdapter

LONG = " filler" * 30


def test_login_markers_come_from_registry(monkeypatch):
    monkeypatch.setitem(registry.DB_REGISTRY["cnki"], "logged_out_markers", ["请登录"])
    assert server._is_logged_in("cnki", "机构登录" + LONG) is True
    assert server._is_logged_in("cnki", "请登录" + LONG) is False


def test_login_steps_come_from_registry(monkeypatch):
    monkeypatch.setitem(registry.DB_REGISTRY["ieee"], "login_steps", ["打开学校VPN"])
    text = server._need_login_response("ieee")[0].text
    assert "1. 打开已启动的 Chrome/Edge 浏览器" in text and "2. 打开学校VPN" in text, text


def test_no_dead_config_or_code():
    for cfg in registry.DB_REGISTRY.values():
        assert not {"sp_url", "target_url_pattern", "cookie_accept"} & set(cfg)
        assert {"logged_in_markers", "logged_out_markers", "login_steps"} <= set(cfg)
    assert not hasattr(CnkiAdapter, "login") and not hasattr(CnkiAdapter, "download")
