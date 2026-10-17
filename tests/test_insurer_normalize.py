import gzip
import json

from ingest.insurers.normalize import network_name, normalize_file

LINE = {
    "billing_code": "73721", "billing_code_type": "CPT", "description": "MRI knee",
    "negotiation_arrangement": "ffs",
    "negotiated_rates": [
        {"ccns": ["030006", "030011"], "provider_references": [1, 3], "negotiated_prices": [
            {"negotiated_type": "negotiated", "negotiated_rate": 412.5, "setting": "outpatient",
             "billing_class": "institutional", "service_code": ["22", "11"],
             "expiration_date": "9999-12-31"}]},
        {"ccns": ["030006"], "provider_references": [7], "negotiated_prices": [  # same price again
            {"negotiated_type": "negotiated", "negotiated_rate": 412.5, "setting": "outpatient",
             "billing_class": "institutional", "service_code": ["11", "22"],
             "expiration_date": "9999-12-31"}]},
    ],
}  # fmt: skip


def test_network_name_from_the_file_name(tmp_path):
    name = "2026-10-01_cigna-health-life-insurance-company_arizona-hmo_in-network-rates.jsonl.gz"
    assert network_name(tmp_path / name) == "arizona-hmo"
    partners = {
        "2026-10-01_sagamorehn_cigna_in-network-rates.jsonl.gz": "sagamorehn_cigna",
        "2026_10_01_priority_health_PPO_in-network-rates.jsonl.gz": "priority_health_PPO",
        "2026-10-01_upper-midwest-affiliation-partner_cigna-ppo_in-network-rates.jsonl.gz":
            "upper-midwest-affiliation-partner_cigna-ppo",
    }  # fmt: skip
    for file, network in partners.items():
        assert network_name(tmp_path / file) == network


def test_one_row_per_hospital_and_price_with_duplicates_removed(tmp_path):
    path = (
        tmp_path
        / "2026-10-01_cigna-health-life-insurance-company_arizona-hmo_in-network-rates.jsonl.gz"
    )
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(LINE) + "\n")
    df = normalize_file(path, "cigna", "2026-10")
    assert sorted(df["ccn"].to_list()) == ["030006", "030011"]  # 030006's repeat collapsed
    row = df.filter(df["ccn"] == "030006").row(0, named=True)
    assert row["negotiated_rate"] == 412.5 and row["service_codes"] == "11,22"
    assert row["network"] == "arizona-hmo" and row["billing_code"] == "73721"
