from serving.services import compact, load_search_terms, search_terms, service_id


def test_compact_keeps_falsy_values():
    assert compact({"a": 0, "b": False, "c": "", "d": None}) == {"a": 0, "b": False, "c": ""}


def test_service_ids():
    assert service_id("CPT/HCPCS:73721") == "cpt-hcpcs:73721"
    assert service_id("MS-DRG:470") == "ms-drg:470"


def test_search_terms_from_the_seed_cover_the_billing_language():
    rules = load_search_terms()
    assert "knee" in search_terms(
        "73721", "MRI EXT LOWER JT WO CNT LT MRI scan of leg joint", rules
    )
    assert "doctor" in search_terms("99213", "OFFICE O/P EST LOW 20 MIN", rules)
    assert search_terms("86003", "ALLERGEN SPECIFIC IGE", rules) is None
