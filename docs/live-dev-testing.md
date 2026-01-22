## Live local-dev backend testing (real OpenAI + SERP + Shopify)

This repo already has `pytest` tests under `src/test/`. This doc is for **black-box local-dev tests** that:

- hit your running FastAPI server over HTTP
- use **real OpenAI** (no mocking)
- use **real SERP enrichment**
- perform **real Shopify writes** (productUpdate + translationsRegister)

The runner is: `scripts/live_dev_tests.py`

---

## Prereqs

- Backend running locally (docker-compose or uvicorn)
- A dev Shopify store where you’re okay with a **single product being mutated** during tests (the script snapshots and restores it by default)
- DB reachable from the script (same `DATABASE_URL` the API uses)

---

## Required environment variables

### Backend target

- `API_BASE_URL` (optional): default `http://localhost:8000`

### Database

- `DATABASE_URL`: the same DB the backend uses (SQLite or Postgres)

### OpenAI (real)

- `OPENAI_API_KEY`

### SERP (real)

- `SERP_API_KEY`
- `SERP_API_URL` (optional; defaults to `https://serpapi.com/search`)

### Shopify (real)

- `SHOPIFY_API_SECRET`: needed to generate a valid App Proxy signature for endpoints that require it
- `TEST_SHOP_DOMAIN`: e.g. `your-dev-shop.myshopify.com`
- `TEST_SHOP_ACCESS_TOKEN`: Admin API access token for that shop
- `TEST_PRODUCT_ID`: numeric product id to mutate (the script will restore it unless disabled)

Optional:

- `SHOPIFY_API_VERSION` (default `2024-07`)
- `LIVE_TEST_TIMEOUT_S` (default `90`)

---

## Run

From `/Users/prithviraj/shopify-translator-api`:

```bash
python scripts/live_dev_tests.py
```

Run the full (more expensive) suite:

```bash
python scripts/live_dev_tests.py --full
```

If you need to keep Shopify untouched (skips mutation tests):

```bash
python scripts/live_dev_tests.py --skip-shopify
```

If you do NOT want the script to restore the Shopify product (not recommended):

```bash
python scripts/live_dev_tests.py --no-restore
```

---

## What the runner covers

### Plan gating

- Basic: streaming forbidden (403)
- Standard: streaming forbidden (403)
- Pro: streaming allowed and increments usage (+1 rewrite)
- Basic: bulk multi-locale forbidden (403)
- Standard: bulk 2 locales allowed
- Pro: bulk 3 locales allowed (**only with `--full`**)

### External enrichments

- Standard/Pro: expects `competitor_results` from SERP (when `SERP_API_KEY` configured)

### Shopify writes

- generate-copy with `product_id`: updates primary locale via `productUpdate`
- bulk with `[secondary, primary]`: updates secondary via `translationsRegister` and primary last
- missing token -> server should 500 on write paths

### Paid grace / expiry corner cases

- Grace active: user plan Free but shop last_plan_name Pro + access_expires_at future → streaming should work
- Expired paid: last_plan_name paid + access_expires_at past → generation should 403

### Input validation & contract checks

- invalid JSON → 400
- missing shop param → 400
- empty/too long description → 422
- invalid tone_profile → 422
- output schema checks: `seo_*` length constraints and mandatory Dimensions header

---

## Safety notes

- **Costs**: these are real OpenAI calls. Keep inputs small; use `--full` only when needed.
- **Shopify mutations**: the script snapshots and restores the chosen product by default. Still, use a dedicated dev product.
- **Locales**: secondary translation testing requires your shop to have at least one published locale besides the primary.

---

## Troubleshooting

- **401/400 on proxy endpoints**:
  - Ensure `SHOPIFY_API_SECRET` is correct and exported for the test runner
  - Ensure `TEST_SHOP_DOMAIN` matches the DB `users.username` and `shops.domain` the script seeds

- **Shopify GraphQL 401**:
  - `TEST_SHOP_ACCESS_TOKEN` invalid/expired
  - App not installed or missing scopes for translations/products

- **SERP enrichment empty**:
  - `SERP_API_KEY` missing/invalid, or SerpAPI returning empty results

- **Streaming test fails**:
  - Confirm Pro plan exists in DB with `can_stream_responses=True` (the script runs `scripts/seed_db.py`)

