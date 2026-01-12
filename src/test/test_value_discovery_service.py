from src.main.service.value_discovery_service import ValueDiscoveryService


def test_value_discovery_no_match_returns_empty_list():
    svc = ValueDiscoveryService()
    out = svc.discover(title="Plain product", description="Nothing special here.")
    assert out == []


def test_value_discovery_kyoto_rule():
    svc = ValueDiscoveryService()
    out = svc.discover(title="Kyoto artisan bowl", description="Handmade in Kyoto.")
    assert len(out) >= 1
    assert out[0]["category"] == "Regional Pedigree"
    assert "Kyoto" in out[0]["evidence_text"] or "京都" in out[0]["evidence_text"]


def test_value_discovery_urushi_rule_detects_japanese_and_english():
    svc = ValueDiscoveryService()
    out = svc.discover(
        title="漆 bowl",
        description="Finished with Urushi in a traditional process.",
    )
    # At least one urushi-related match must be returned
    assert any(d["title"] == "Urushi Lacquer Story" for d in out)
    # Evidence should be one of the triggering substrings
    assert any(d["evidence_text"] in ("漆", "Urushi", "urushi") for d in out)


