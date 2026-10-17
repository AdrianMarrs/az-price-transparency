import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("deploy_site", Path("scripts/deploy_site.py"))
deploy_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_site)


def test_hashed_assets_cache_for_a_year_and_index_never():
    assert "immutable" in deploy_site.cache_control("assets/index-0raOsava.js")
    assert deploy_site.cache_control("index.html") == "no-cache"


def test_content_types():
    assert deploy_site.content_type("index.html") == "text/html"
    assert deploy_site.content_type("assets/index.css") == "text/css"
    assert deploy_site.content_type("assets/index.js") in (
        "text/javascript",
        "application/javascript",
    )


def test_pages_and_their_data_revalidate():
    assert deploy_site.cache_control("hospitals/030006/index.html") == "no-cache"
    assert deploy_site.cache_control("hospitals/030006.data") == "no-cache"
    assert "immutable" in deploy_site.cache_control("assets/inline/0123456789abcdef.js")
    assert deploy_site.content_type("hospitals/030006.data") == "text/x-script"
