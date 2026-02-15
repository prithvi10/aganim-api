from src.ecommerce.config.configs import DISCOVERY_MAP, MADE_IN_JAPAN_GLOSSARY


def test_discovery_map_has_entry_for_every_glossary_key():
    # DISCOVERY_MAP may contain extra entries (e.g., "Kyoto"), but every glossary key
    # must exist as a DISCOVERY_MAP key to ensure deterministic discovery outputs.
    for key in MADE_IN_JAPAN_GLOSSARY.keys():
        assert key in DISCOVERY_MAP, f"Missing DISCOVERY_MAP entry for glossary key: {key!r}"


