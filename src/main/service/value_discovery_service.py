from __future__ import annotations

import re
from typing import Any

from src.main.config.configs import MADE_IN_JAPAN_GLOSSARY, DISCOVERY_MAP


class ValueDiscoveryService:
    """
    Evidence-Discovery engine.

    Strict logic:
    - Uses regex patterns from MADE_IN_JAPAN_GLOSSARY to scan product title+description.
    - Returns [] if no evidence is found.
    - Emits one "Discovery Object" per regex match (JSON-serializable dict).
    """

    # Minimal explicit rules requested by product:
    # - If Kyoto is found, suggest "Regional Pedigree"
    KYOTO_PATTERN = re.compile(r"(?:\bKyoto\b|京都)", re.IGNORECASE)

    # Curated mapping for deterministic outputs (no LLM here).
    # Defined in configs.py as DISCOVERY_MAP

    def discover(self, *, title: str | None, description: str | None) -> list[dict[str, Any]]:
        text_title = title or ""
        text_desc = description or ""
        full_text = f"{text_title}\n{text_desc}"

        discoveries: list[dict[str, Any]] = []

        # Special Kyoto rule (requested explicitly)
        for m in self.KYOTO_PATTERN.finditer(full_text):
            rule = DISCOVERY_MAP["Kyoto"]
            discoveries.append(
                {
                    "category": rule["category"],
                    "title": rule["title"],
                    "evidence_text": m.group(0),
                    "suggested_content": rule["suggested_content"],
                }
            )

        # Glossary-driven rules
        for raw_key, meta in (MADE_IN_JAPAN_GLOSSARY or {}).items():
            key = str(raw_key).strip()
            pat = str(meta.get("match") or "").strip()
            if not key or not pat:
                continue

            compiled = re.compile(pat, re.IGNORECASE)
            for m in compiled.finditer(full_text):
                rule = DISCOVERY_MAP.get(key)
                # If we don't have a curated rule, skip (strict logic: only suggest when we know what to suggest)
                if not rule:
                    continue
                discoveries.append(
                    {
                        "category": rule["category"],
                        "title": rule["title"],
                        "evidence_text": m.group(0),
                        "suggested_content": rule["suggested_content"],
                    }
                )

        return discoveries


