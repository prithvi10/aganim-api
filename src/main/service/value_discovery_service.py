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
        seen_titles: set[str] = set()

        def _add_discovery(*, rule: dict[str, Any], evidence_text: str) -> None:
            """
            Deduplicate by rule title (not by evidence occurrence).
            This prevents duplicate cards like "Regional Pedigree" appearing multiple
            times when the same keyword is present in both title and description.
            """
            title_key = str(rule.get("title") or "").strip()
            if not title_key or title_key in seen_titles:
                return
            seen_titles.add(title_key)
            discoveries.append(
                {
                    "category": rule["category"],
                    "title": rule["title"],
                    "evidence_text": evidence_text,
                    "suggested_content": rule["suggested_content"],
                }
            )

        # Special Kyoto rule (requested explicitly)
        for m in self.KYOTO_PATTERN.finditer(full_text):
            rule = DISCOVERY_MAP["Kyoto"]
            _add_discovery(rule=rule, evidence_text=m.group(0))

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
                _add_discovery(rule=rule, evidence_text=m.group(0))

        return discoveries


