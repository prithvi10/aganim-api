#!/usr/bin/env python3
"""
Brand Soul Comparison Script

Calls the rewrite API twice (with/without brand soul enabled via the shop toggle)
and compares outputs side-by-side.

Usage:
    python scripts/tests/brand_soul_comparison.py \
        --shop test-crossborder-connect-new.myshopify.com \
        --product "若狭塗箸セット" \
        --description "福井県小浜市の伝統工芸若狭塗の夫婦箸セット..." \
        --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time
import requests


BRAND_KEYWORDS = [
    "heritage", "artisan", "craftsmanship", "handcrafted", "tradition",
    "authentic", "lacquer", "Wakasa", "master", "heirloom",
]

BANNED_WORDS = [
    "mass-produced", "cheap", "disposable", "synthetic", "generic",
]


def toggle_brand_soul(api_url: str, shop: str, enabled: bool) -> bool:
    """Toggle the shop's brand_soul_enabled setting."""
    resp = requests.put(
        f"{api_url}/api/admin/brand-soul-toggle",
        json={"shop": shop, "enabled": enabled},
    )
    if resp.status_code != 200:
        print(f"  Toggle returned {resp.status_code}: {resp.text[:200]}")
    return resp.status_code == 200


def generate_rewrite(api_url: str, shop: str, product_name: str, description: str, target_locale: str = "en") -> dict:
    """Call the rewrite endpoint and return the result."""
    resp = requests.post(
        f"{api_url}/api/proxy/generate-copy",
        params={"shop": shop},
        json={
            "product_name": product_name,
            "japanese_description": description,
            "category": "General",
            "target_locale": target_locale,
            "brand_soul_enabled": True,
        },
    )
    if resp.status_code != 200:
        print(f"  ERROR: {resp.status_code} — {resp.text[:200]}")
        return {}
    data = resp.json()
    print(f"  OK — keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    return data


def extract_text(result: dict) -> str:
    """Extract the generated description from the API response, trying multiple key paths."""
    if not result:
        return ""
    # Direct keys
    for key in ("description", "rewritten_description", "english_description"):
        val = result.get(key, "")
        if val:
            return str(val)
    # Nested under "data"
    if isinstance(result.get("data"), dict):
        for key in ("description", "rewritten_description"):
            val = result["data"].get(key, "")
            if val:
                return str(val)
    return ""


def score_output(text: str, keywords: list[str], banned: list[str]) -> dict:
    """Score the output for brand keyword presence."""
    text_lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in text_lower]
    banned_found = [bw for bw in banned if bw.lower() in text_lower]
    return {
        "word_count": len(text.split()),
        "keywords_found": len(found),
        "keywords_total": len(keywords),
        "keywords_list": found,
        "banned_found": len(banned_found),
        "banned_list": banned_found,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare AI output with/without brand soul")
    parser.add_argument("--shop", required=True, help="Shop domain")
    parser.add_argument("--product", required=True, help="Product name (Japanese)")
    parser.add_argument("--description", required=True, help="Product description (Japanese)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--locale", default="en", help="Target locale")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Brand Soul Comparison")
    print(f"  Shop: {args.shop}")
    print(f"  Product: {args.product}")
    print(f"  Target: {args.locale}")
    print(f"{'='*60}\n")

    # --- WITH brand soul ---
    print("[1/4] Enabling brand soul...")
    toggle_brand_soul(args.api_url, args.shop, True)
    time.sleep(1)

    print("[2/4] Generating WITH brand soul...")
    with_result = generate_rewrite(args.api_url, args.shop, args.product, args.description, args.locale)
    with_text = extract_text(with_result)

    # --- WITHOUT brand soul ---
    print("[3/4] Disabling brand soul...")
    toggle_brand_soul(args.api_url, args.shop, False)
    time.sleep(1)

    print("[4/4] Generating WITHOUT brand soul...")
    without_result = generate_rewrite(args.api_url, args.shop, args.product, args.description, args.locale)
    without_text = extract_text(without_result)

    # Re-enable brand soul
    toggle_brand_soul(args.api_url, args.shop, True)

    # --- Score ---
    with_score = score_output(with_text, BRAND_KEYWORDS, BANNED_WORDS)
    without_score = score_output(without_text, BRAND_KEYWORDS, BANNED_WORDS)

    # --- Display ---
    print(f"\n{'='*60}")
    print("  WITH Brand Soul:")
    print(f"{'='*60}")
    print(with_text[:500] if with_text else "(empty)")
    print(f"\n  Keywords: {with_score['keywords_found']}/{with_score['keywords_total']} ({', '.join(with_score['keywords_list']) or 'none'})")
    print(f"  Banned: {with_score['banned_found']} ({', '.join(with_score['banned_list']) or 'none'})")
    print(f"  Word count: {with_score['word_count']}")

    print(f"\n{'='*60}")
    print("  WITHOUT Brand Soul:")
    print(f"{'='*60}")
    print(without_text[:500] if without_text else "(empty)")
    print(f"\n  Keywords: {without_score['keywords_found']}/{without_score['keywords_total']} ({', '.join(without_score['keywords_list']) or 'none'})")
    print(f"  Banned: {without_score['banned_found']} ({', '.join(without_score['banned_list']) or 'none'})")
    print(f"  Word count: {without_score['word_count']}")

    # --- Verdict ---
    kw_diff = with_score["keywords_found"] - without_score["keywords_found"]
    wc_diff = with_score["word_count"] - without_score["word_count"]
    pct = (wc_diff / max(without_score["word_count"], 1)) * 100

    print(f"\n{'='*60}")
    print(f"  VERDICT:")
    if kw_diff > 0:
        print(f"  Brand soul adds context (+{kw_diff} keywords, {'+' if pct >= 0 else ''}{pct:.0f}% length)")
    elif kw_diff == 0:
        print(f"  No keyword difference detected. Brand soul may not be influencing output.")
    else:
        print(f"  Unexpected: fewer brand keywords WITH brand soul ({kw_diff})")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
