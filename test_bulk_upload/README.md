# Bulk Upload Test Data

Ready-to-upload test files for the Bulk Upload Missions feature (Pro plan only).

## Files

```
test_bulk_upload/
├── text_only/
│   └── products.csv          ← Upload this for "Bulk Text Only" mission
├── full_launch/
│   ├── products.csv           (reference — packaged inside the ZIP)
│   └── images/
│       ├── matcha_powder.jpg
│       ├── chopstick_set.jpg
│       ├── arita_bowl.jpg
│       ├── furoshiki.jpg
│       └── maneki_neko.jpg
├── full_launch_upload.zip     ← Upload this for "Bulk Full Launch" mission
├── generate_test_data.py      (regenerate images if needed)
└── README.md
```

## Test Products (5 items)

| row_id | Product | Category | Market |
|--------|---------|----------|--------|
| R001 | 宇治抹茶パウダー 100g | Tea & Beverages | en |
| R002 | 手作り箸セット 夫婦箸 桐箱入り | Kitchen & Dining | en |
| R003 | 有田焼 茶碗 藍染花紋 | Home & Kitchen | en |
| R004 | 風呂敷 大判 70cm 京友禅 | Accessories | en |
| R005 | 招き猫 九谷焼 4号 | Home Decor | en |

## How to Test

### Mission 1 — Text Only (CSV)

1. Go to **Missions** → select **Bulk Text Upload**
2. Upload `text_only/products.csv`
3. Set preferences (tone, Brand Soul, etc.)
4. Confirm and launch
5. Pipeline: **RewriterAgent → SEOAgent** for each product
6. Products created as **DRAFT** in Shopify

### Mission 2 — Full Launch (ZIP)

1. Go to **Missions** → select **Bulk Full Launch**
2. Upload `full_launch_upload.zip`
3. Set preferences
4. Confirm and launch (check image credit preview)
5. Pipeline: **RewriterAgent → ImageRefinementAgent → SEOAgent** for each product
6. Products created as **DRAFT** with refined images in Shopify

## CSV Column Reference

| Column | Required | Description |
|--------|----------|-------------|
| `row_id` | Yes | Unique row identifier |
| `product_name_ja` | Yes | Product name in Japanese |
| `description_ja` | Yes | Product description in Japanese |
| `category` | Yes | Shopify product type / category |
| `target_market` | Yes | Target locale code (e.g. `en`, `zh-TW`) |
| `image_ref` | Full Launch only | Filename matching a file in `images/` folder |

Any extra columns are silently ignored.

## Regenerating Images

If you need fresh placeholder images:

```bash
python test_bulk_upload/generate_test_data.py
```

Requires `Pillow` (`pip install Pillow`).
