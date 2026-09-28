"""
Database adapter registry — add new databases here.

Adapting to another institution / account type: edit the three login fields of each
database. They are checked against the text of the database's home page:
  logged_in_markers   regexes; if any matches, the user counts as logged in
  logged_out_markers  regexes; otherwise, if any matches, the user counts as logged out
                      (no match at all also counts as logged in)
  login_steps         what the user is told to do in the browser when not logged in
"""

DB_REGISTRY = {

    "ieee": {
        "name": "ieee",
        "label": "IEEE Xplore",
        "home_url": "https://ieeexplore.ieee.org/Xplore/home.jsp",
        "adapter": "carsi_search.databases.ieee:IeeeAdapter",
        "logged_in_markers": [],
        "logged_out_markers": ["Institutional Sign In"],
        "login_steps": [
            "访问 https://ieeexplore.ieee.org/Xplore/home.jsp",
            "点击 Institutional Sign In",
            "完成机构认证",
        ],
    },

    "sciencedirect": {
        "name": "sciencedirect",
        "label": "ScienceDirect (Elsevier)",
        "home_url": "https://www.sciencedirect.com/",
        "adapter": "carsi_search.databases.sciencedirect:ScienceDirectAdapter",
        "logged_in_markers": ["(?i)institutional access via", "Sign in via"],
        "logged_out_markers": ["Sign in"],
        "login_steps": [
            "访问 https://www.sciencedirect.com",
            "点击 Sign in → Sign in via your institution",
            "完成机构认证",
        ],
    },

    "cnki": {
        "name": "cnki",
        "label": "CNKI 知网",
        "home_url": "https://kns.cnki.net/kns8s/search",
        "adapter": "carsi_search.databases.cnki:CnkiAdapter",
        "logged_in_markers": [],
        "logged_out_markers": ["机构登录", "校外访问"],
        "login_steps": [
            "访问 https://kns.cnki.net",
            "点击「机构登录」→「校外访问」",
            "选择学校并完成认证",
        ],
    },
}


def get_db(name: str) -> dict | None:
    return DB_REGISTRY.get(name)


def list_dbs() -> list[str]:
    return list(DB_REGISTRY.keys())


def _import_adapter(adapter_path: str):
    import importlib
    module_path, class_name = adapter_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


async def get_adapter(name: str, page):
    db = get_db(name)
    if not db:
        raise ValueError(f"Unknown database: {name}. Available: {list_dbs()}")
    cls = _import_adapter(db["adapter"])
    return cls(page)
