"""National discovery's name matching (no network)."""

from ingest.national.discover import Index, Websites, best_entry, name_score, site_root


def wiki(label, website, state="AZ", city=""):
    return {"itemLabel": label, "website": website, "stateCode": f"US-{state}", "cityLabel": city}


def test_distinctive_words_tell_hospitals_of_one_system_apart():
    assert name_score("BANNER DESERT MEDICAL CENTER", "Banner Desert Medical Center") == 1.0
    assert name_score("BANNER DESERT MEDICAL CENTER", "Banner Del E. Webb Medical Center") < 0.75
    assert name_score("ST JOSEPH'S HOSPITAL", "Saint Josephs Hospital") == 1.0


def test_best_entry_does_not_guess_between_two_equal_names():
    entries = [{"location-name": "Mercy Hospital", "mrf-url": "a"},
               {"location-name": "Mercy Hospital", "mrf-url": "b"}]  # fmt: skip
    assert best_entry("MERCY HOSPITAL", entries) == (None, 1.0)
    assert best_entry("ANY NAME", entries[:1])[0]["mrf-url"] == "a"  # a one-location file


def test_site_root():
    assert site_root("www.x.org/about") == "https://www.x.org"
    assert site_root("http://X.org:8080/") == "https://x.org"
    assert site_root("") is None and site_root("localhost") is None


def test_wikidata_website_needs_the_same_state_and_a_near_exact_name():
    w = Websites([wiki("Tucson Medical Center", "https://www.tmcaz.com/", city="Tucson"),
                  wiki("Tucson Medical Center", "https://elsewhere.org", state="NM")])  # fmt: skip
    assert w.match("TUCSON MEDICAL CENTER", "TUCSON", "AZ") == "https://www.tmcaz.com"
    assert w.match("TUCSON MEDICAL CENTER", "TUCSON", "TX") is None
    assert w.match("NORTHWEST MEDICAL CENTER", "TUCSON", "AZ") is None


def test_wikidata_two_websites_for_a_name_is_no_match():
    w = Websites([wiki("Mercy Hospital", "https://a.org", city="Springfield"),
                  wiki("Mercy Hospital", "https://b.org", city="Springfield")])  # fmt: skip
    assert w.match("MERCY HOSPITAL", "SPRINGFIELD", "AZ") is None


def test_wikidata_short_name_needs_its_city():
    w = Websites([wiki("Holy Cross Hospital", "https://hc.org", city="Nogales")])
    assert w.match("HOLY CROSS HOSPITAL", "NOGALES", "AZ") == "https://hc.org"
    assert w.match("HOLY CROSS HOSPITAL", "TUCSON", "AZ") is None


def test_system_match_needs_city_or_three_words():
    text = "location-name: Holy Cross Hospital\nmrf-url: https://h.org/f.csv\n"
    index = Index({"https://h.org": ("found", text)})
    assert index.match("HOLY CROSS HOSPITAL", "TAOS") is None
    assert index.match("HOLY CROSS HOSPITAL", "") is None


def entries(*names):
    return [{"location-name": n, "mrf-url": f"https://x/{i}.csv"} for i, n in enumerate(names)]


def test_an_exact_name_wins_over_a_longer_one():
    found, score = best_entry("GOOD SAMARITAN HOSPITAL",
                              entries("GOOD SAMARITAN HOSPITAL", "GOOD SAMARITAN HOSPITAL-MISSION OAKS"))  # fmt: skip
    assert found["mrf-url"] == "https://x/0.csv" and score == 1.0


def test_a_brand_before_the_dash_or_in_the_host_is_set_aside():
    kaiser = entries("Vacaville Medical Center", "Vallejo Medical Center")
    assert (
        best_entry("KAISER FOUNDATION HOSPITAL - VACAVILLE", kaiser)[0]["mrf-url"]
        == "https://x/0.csv"
    )
    mercy = entries("Defiance Hospital", "Mercy West Hospital")
    assert (
        best_entry("MERCY DEFIANCE HOSPITAL", mercy, "www.mercy.com")[0]["mrf-url"]
        == "https://x/0.csv"
    )
    assert best_entry("MERCY DEFIANCE HOSPITAL", mercy)[0] is None  # no brand known


def test_without_its_brand_a_hospital_still_needs_every_word():
    kaiser = entries("San Jose Medical Center", "Vallejo Medical Center")
    assert best_entry("KAISER FOUNDATION HOSPITAL - SAN JOSE NORTH", kaiser)[0] is None
    assert (
        best_entry("KAISER FOUNDATION HOSPITAL - NORTH", entries("North Campus", "South"))[0]
        is None
    )
