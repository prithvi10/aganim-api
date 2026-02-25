"""
Rakuten Genre Item Scraper
Scrapes 1 item from each major genre on rakuten.co.jp daily ranking pages.
Outputs: item name, description, and image URL per genre.
"""

import json
import time
import requests
from typing import Optional, Dict, List
from bs4 import BeautifulSoup

# Genre IDs sourced from https://ranking.rakuten.co.jp/daily/
GENRES = {
    "レディースファッション (Ladies Fashion)": "100371",
    "メンズファッション (Men's Fashion)": "551177",
    "インナー・下着・ナイトウェア (Underwear & Nightwear)": "100433",
    "バッグ・小物・ブランド雑貨 (Bags & Accessories)": "216131",
    "靴 (Shoes)": "558885",
    "腕時計 (Watches)": "558929",
    "ジュエリー・アクセサリー (Jewelry)": "216129",
    "食品 (Food)": "100227",
    "スイーツ・お菓子 (Sweets)": "551167",
    "水・ソフトドリンク (Beverages)": "100316",
    "ビール・洋酒 (Beer & Spirits)": "510915",
    "日本酒・焼酎 (Sake & Shochu)": "510901",
    "日用品雑貨・文房具・手芸 (Daily Goods & Stationery)": "215783",
    "キッチン用品・食器 (Kitchen & Tableware)": "558944",
    "インテリア・寝具・収納 (Interior & Bedding)": "100804",
    "美容・コスメ・香水 (Beauty & Cosmetics)": "100939",
    "ダイエット・健康 (Diet & Health)": "100938",
    "医薬品・コンタクト・介護 (Medicine & Contacts)": "551169",
    "キッズ・ベビー・マタニティ (Kids & Baby)": "100533",
    "おもちゃ (Toys)": "566382",
    "家電 (Home Appliances)": "551176",
    "TV・オーディオ・カメラ (TV/Audio/Camera)": "211742",
    "パソコン・周辺機器 (PC & Peripherals)": "100026",
    "スマートフォン・タブレット (Smartphones)": "564500",
    "ゴルフ (Golf)": "101077",
    "スポーツ・アウトドア (Sports & Outdoor)": "101070",
    "車用品・バイク用品 (Auto & Bike Parts)": "503190",
    "花・ガーデン・DIY (Flowers & DIY)": "100005",
    "ペット・ペットグッズ (Pets)": "101213",
    "本・雑誌・コミック (Books & Comics)": "200162",
    "CD・DVD": "101240",
    "テレビゲーム (Video Games)": "101205",
    "ホビー (Hobbies)": "101164",
    "楽器・音響機器 (Musical Instruments)": "112493",
}

RANKING_URL = "https://ranking.rakuten.co.jp/daily/{genre_id}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def scrape_genre(genre_name: str, genre_id: str, max_retries: int = 3) -> Optional[Dict]:
    """Fetch the daily ranking page for a genre and extract the #1 item."""
    url = RANKING_URL.format(genre_id=genre_id)
    resp = None
    for attempt in range(max_retries):
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  [RETRY {attempt+1}/{max_retries}] {e} — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"  [ERROR] Request failed after {max_retries} attempts: {e}")
                return None
    if resp is None:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Top-3 items are in .rnkRanking_top3box, items 4+ in .rnkRanking_after4box.
    item_box = soup.select_one(".rnkRanking_top3box")
    if not item_box:
        item_box = soup.select_one(".rnkRanking_after4box")
    if not item_box:
        print("  [WARN] No ranking item box found")
        return None

    name_el = item_box.select_one(".rnkRanking_itemName")
    name = name_el.get_text(strip=True) if name_el else ""

    image_url = ""
    img_el = item_box.select_one(".rnkRanking_imageBox img")
    if img_el:
        image_url = img_el.get("src", "") or img_el.get("data-src", "")

    alt_text = img_el.get("alt", "").strip() if img_el else ""
    description = alt_text if alt_text and alt_text != name else name

    link_el = item_box.select_one("a[href]")
    item_url = link_el["href"] if link_el else ""

    if not name:
        print("  [WARN] Could not extract item name")
        return None

    return {
        "genre": genre_name,
        "name": name,
        "description": description,
        "image_url": image_url,
        "item_url": item_url,
    }


def main():
    results: List[Dict] = []
    failed: List[str] = []

    print("=" * 80)
    print("  Rakuten Genre Item Scraper")
    print(f"  Scraping the #1 daily-ranked item from each of {len(GENRES)} genres")
    print("=" * 80)

    for i, (genre_name, genre_id) in enumerate(GENRES.items(), 1):
        print(f"\n[{i:>2}/{len(GENRES)}] {genre_name}")

        item = scrape_genre(genre_name, genre_id)
        if item:
            results.append(item)
            display_name = item["name"][:70]
            print(f"       Name:  {display_name}{'...' if len(item['name']) > 70 else ''}")
            print(f"       Image: {item['image_url'][:90]}")
        else:
            failed.append(genre_name)
            print("       FAILED - could not extract item")

        time.sleep(0.5)

    # ── Print summary ──
    print("\n" + "=" * 80)
    print(f"  RESULTS: {len(results)} items found, {len(failed)} genres failed")
    print("=" * 80)

    for item in results:
        print(f"\n{'─' * 60}")
        print(f"  Genre:       {item['genre']}")
        print(f"  Name:        {item['name']}")
        print(f"  Description: {item['description']}")
        print(f"  Image URL:   {item['image_url']}")
        print(f"  Item URL:    {item['item_url']}")

    if failed:
        print(f"\n  Failed genres ({len(failed)}): {', '.join(failed)}")

    # ── Save JSON ──
    output_path = "scripts/rakuten_items.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()
