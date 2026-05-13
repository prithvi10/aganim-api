# Aganim AI — Proposal

## 1) Executive Summary (1-sentence)

Build a Japan-first AI Shopify app that turns Japanese product data into polished multilingual product pages, optimizes SEO, analyzes competitor pricing, generates marketing content & visuals, and orchestrates multi-agent workflows — target ~7k–10k Japan Shopify merchants who want to sell overseas; with a mid-tier ~$60/mo (~¥9,000) ARPU you can hit ¥10M/yr with ~100 paying merchants.

## 2) Market Context & Validation (short, evidence-backed)

**Shopify store footprint in Japan:** recent trackers show tens of thousands of active Shopify stores in Japan (reports in 2025 show ~30k–42k live stores). That gives a reasonably large addressable base for a Japan-first app.

**Merchants are expanding cross-border:** many Shopify Japan case studies (big D2C brands) demonstrate Shopify is used for global / D2C expansion — merchants care about translation, customer support, and multi-channel ops. This supports a product that removes language friction.

**Local channels matter:** LINE is a dominant customer touchpoint in Japan; merchants commonly integrate LINE with Shopify for CRM and customer messages — integrating LINE/LINE Official Account raises adoption chances. (Note: LINE integration is on the future roadmap, not yet built.)

**Existing translation apps exist (proof of demand):** solutions like Weglot are popular on Shopify (global players exist), but they are not Japan-specialized agents (tone/culture/keigo + SEO + competitive pricing + visual pipeline + agentic workflows is Aganim's differentiation).

**Implication:** a Japan-first, AI-powered translation + SEO + pricing + marketing + visual platform is well positioned — the market exists and merchants already use translation apps.

## 3) Product Strategy & Positioning

**Value proposition (single line):**
"Make your Japanese shop speak global sales-grade in 12+ languages — product pages, SEO, competitive pricing, marketing content, and AI-generated visuals — without hiring translators or agencies."

**Target buyer personas (Japan Shopify merchants):**
- Small/medium D2C brands (cosmetics, craft, home goods) expanding to US/EU/ASEAN
- Export-focused merchants selling on Shopify + marketplaces
- Agencies/managers running multiple stores that need bulk localization

**Core differentiators:**
- Japanese linguistic quality (keigo, nuance, marketing tone) with a **Japanese craftsmanship glossary** (14 traditional terms: Urushi, Kintsugi, Bizen-yaki, Nambu Tekki, etc.) — not machine-literal translations.
- **Brand Soul system**: extracts brand voice from URLs and uploaded files to maintain consistent tone across all generated content.
- **12+ target locales** (en, ja, zh-TW, ko, de, fr, es, it, pt, th, vi, zh-CN) with locale-specific personas.
- **Integrated AI agents** that can: rewrite descriptions, generate SEO titles/metadata with SERP analysis, analyze competitor pricing, generate social hooks/ad copy/email templates, and produce AI-generated product images.
- **Multi-agent mission orchestration**: chain rewriter → SEO → pricing → marketing → visual into a single automated pipeline.
- Deep Shopify integration (bulk catalog processing, webhooks, product translations via GraphQL, billing API, App Bridge v4).

## 4) Feature Roadmap

### Shipped Features (Current State)
- Shopify App + OAuth install flow with App Bridge v4
- Bulk product fetch (unlimited for paid tiers)
- AI product rewrite (JA → 12+ languages) with Brand Soul-aware tone
- SEO optimizer with SERP analysis (via SerpAPI), LSI keyword enrichment, CTR/PST scoring
- Price Scout: competitor pricing via Google Shopping, statistical market analysis, AI pricing recommendation
- Marketing Studio: social hooks (Instagram Reels, TikTok), seasonal campaigns, email templates, ad copy, blog posts
- Visual Pipeline: background removal (rembg), AI image generation (FLUX 2.0 Pro via fal.ai), marketing typography (Ideogram 3.0), image refinement (Nano Banana)
- Brand Soul: URL scraping, file upload with GPT-4o vision extraction, brand archetype wizard, RAG vector store with pgvector
- Multi-agent missions with SSE streaming, state persistence, and user corrections
- 4-tier billing (Free / Basic $39 / Standard $89 / Pro $199) with 7-day free trial
- SuperAdmin portal (merchant management, outreach, support triage)
- Lifecycle emails via Amazon SES (welcome, upgrade confirmation, credit limit nudge, feedback requests)
- i18n UI (English + Japanese)
- GDPR compliance webhooks
- Shopify Admin UI Action extension (trigger AI from product detail page)

### v-next (Near-term Roadmap)
- Translation memory & editable glossary (merchant-managed brand terms preservation)
- AI email reply composer (generate English replies from Japanese customer messages)
- LINE integration (order status, cart recovery messages, support triggers)
- Social posting automation (publish to Instagram/Twitter/Facebook via Buffer or direct APIs)
- Marketplace CSV export templates (Amazon US, Etsy) & batch sync
- Role + team management (multiple users)
- Admin UX for tone presets (casual / formal / marketing)

### v-future (6–18 months)
- Chatbot module for storefront (Shopify Inbox) answering in English using store context
- Fine-tunable translation models (custom prompts / brand voice) and private model options for large brands
- AI agent workflows (e.g., "handle refund request in English, create ticket, suggest follow-up")
- Performance dashboards: CS deflection, time saved, uplifted conversions (A/B experiment hooks)
- Marketplace direct integrations (Amazon Selling Partner API, eBay)
- Partner program + white-label for agencies

## 5) Technical Architecture (practical + scalable)

### High-level components

**Frontend:** React Router 7 (SSR, successor to Remix) + Shopify Polaris + Tailwind CSS + Framer Motion. React Three Fiber + Drei for the landing page 3D experience. TypeScript. Deployed on Render (Docker, Node 20 Alpine).

**Backend:** Python 3.13 + FastAPI + Uvicorn. Deployed on Render (Docker container). Three-layer architecture: `agentic_core/` (generic AI platform, zero Shopify dependencies), `ecommerce/` (Shopify domain layer), `shared/` (infrastructure).

**DB:** PostgreSQL + pgvector (vector embeddings for RAG). Separate Prisma-managed PostgreSQL for UI session storage.

**Storage:** Cloudflare R2 (primary — visual assets, product images). AWS S3 (legacy).

**AI stack:**
- OpenAI GPT-4o-mini (default), GPT-4o (Pro tier) for all text generation and translation. No separate translation engine (DeepL/Google Translate) — all translation is done via LLM prompts with locale-specific personas.
- fal.ai for image generation: FLUX 2.0 Pro (backgrounds), Ideogram 3.0 (typography/marketing), Nano Banana (image refinement).
- rembg (onnxruntime CPU) for product background removal.
- text-embedding-3-small (1536-dim) for RAG vector embeddings.
- SerpAPI for SERP analysis (SEO) and Google Shopping competitor pricing.
- $150 per-shop fair-use cost cap with degraded model throttling.

**Shopify integration:** Shopify Admin API (GraphQL), Translation API, webhooks (app/install, app/uninstalled, app_subscriptions/update, GDPR compliance). Shopify Billing API for recurring subscriptions. App Bridge v4 for embedded auth.

**Email:** Amazon SES for lifecycle emails (welcome, upgrade, credit limit, feedback, outreach).

**Monitoring:** Sentry SDK for error tracking. Structured logging (app, error, security logs).

**CI/CD:** GitHub Actions for CI (pytest on PR, Alembic migration checks). Render deploy hooks for CD on merge to main.

**Security & compliance:** HMAC-SHA256 (webhook/proxy verification), JWT session tokens, rate limiting (sliding window per IP), TLS, secrets manager, GDPR webhook handlers, structured security audit logging.

### Cost & rate considerations

Use batching + token limits + fair-use cost cap ($150/shop) to control per-merchant AI costs. Cache outputs, reuse across product variants. Image generation costs (fal.ai) gated by tier-based image credit limits. Charge higher tiers for heavier usage.

## 6) Privacy, Legal & Compliance (Japan + export)

**Japan APPI:** handle personal info per APPI; maintain clear privacy policy in Japanese.

**Cross-border data transfer:** when processing product content via OpenAI/fal.ai APIs, disclose in TOS. Product data (not customer PII) is the primary data sent to third-party AI APIs.

**GDPR compliance:** full webhook handlers for `customers/data_request`, `customers/redact`, `shop/redact`. Compliance management page in-app.

**Payment & billing:** Shopify Billing API for all charges. Handle VAT/GST for EU customers when selling internationally.

**Terms:** explicit consent for social content generation on merchant channels.

## 7) Pricing Strategy & Revenue Model (concrete)

### Recommended bundled tiers ($)

| Feature | Free | Basic ($39/mo) | Standard ($89/mo) | Pro ($199/mo) |
|---|---|---|---|---|
| Product Limit | 10 lifetime | 50/mo | Unlimited | Unlimited |
| Missions | 3 lifetime | 1/mo (text-only) | 3/mo (text+full) | Unlimited |
| Image Credits | 5 lifetime | 0 | 10/mo | 100/mo |
| AI Quality | GPT-4o-mini | GPT-4o-mini | GPT-4o-mini | GPT-4o |
| Rewriter | ✓ | ✓ | ✓ | ✓ |
| Marketing Studio | ✓ | ✓ | ✓ | ✓ |
| SEO Optimizer | — | — | ✓ | ✓ |
| Price Scout | — | — | ✓ | ✓ |
| Image Refinement | — | — | ✓ | ✓ |
| Visual Pipeline | — | — | — | ✓ |
| Autonomous Mode | — | — | — | ✓ |
| Multi-Locale Bulk | — | — | — | ✓ |
| Trial | 7-day | 7-day | 7-day | 7-day |
| Support | Email | Email | Priority Email | Live Chat / 1-on-1 Setup |

### Pricing rationale

Translation + SEO + competitive pricing + marketing content + AI visuals is high value for merchants; $39–$199/mo for multi-channel automation is reasonable compared to hiring freelance translators, SEO consultants, or agencies.

### Revenue scenarios (Tentative)

Assume Japan store count conservatively: 30,000 (sources vary 30k–42k).

| Penetration | Paying stores | Avg ARPU | Monthly revenue | Annual revenue |
|---|---|---|---|---|
| 0.3% | 90 | ¥9,000 (~$60) | ¥810,000 | ¥9.72M |
| 1.0% | 300 | ¥9,000 (~$60) | ¥2,700,000 | ¥32.4M |
| 2.0% | 600 | ¥10,500 (~$70) | ¥6,300,000 | ¥75.6M |
| 5.0% | 1,500 | ¥13,500 (~$90) | ¥20,250,000 | ¥243M |

Key takeaways: reaching ~100 paying merchants at ~¥9,000/mo (~$60) ARPU gets you near ¥10M/year. Hitting 1% penetration with current pricing significantly exceeds that target.

## 8) Unit Economics & Rough Cost Model (first 12 months)

### Assumptions (monthly)

- Cloud infra (Render) + PostgreSQL + Cloudflare R2 + CDN: ¥30k–¥100k
- AI inference — OpenAI (depends on usage): ¥50–¥200 per merchant/month
- Image generation — fal.ai: ¥30–¥150 per merchant/month (Pro tier heavy)
- SerpAPI (SEO + Price Scout): ¥10k–¥50k/month depending on query volume
- Amazon SES email: ¥5k–¥10k/month
- Sentry monitoring: ¥5k/month
- Support & ops: 1 person ¥400k/month part-time, ramping up
- Marketing: ¥100k/month initial (ads, content)
- Dev payroll (founder(s) initially) — if hiring: senior dev ¥800k–¥1.2M/month
- Internal safeguard: $150 fair-use cost cap per shop

### Example simple monthly P&L at 300 paid merchants (~$60 ARPU):

- Revenue: ¥2,700k
- AI costs (OpenAI + fal.ai, 300×¥300 avg): ¥90k
- SerpAPI: ¥30k
- Infra & tools (Render, R2, SES, Sentry): ¥150k
- Support/ops: ¥300k (part-time + shared)
- Marketing: ¥100k
- Net (approx): ¥2,030k/month (~¥24.4M/yr) before founder salaries

To scale: optimize AI token costs via caching, batching, and tiered image credit limits.

## 9) Go-to-Market (GTM) Strategy — channels & tactics

### Primary channels (high ROI in Japan)

- **Shopify App Store** — optimize listing in Japanese & English; get featured by Shopify JP via case studies. Leverage the Admin UI Action extension for in-context discovery.
- **Shopify Partners & Japanese agencies** — partner with dev shops who deploy Shopify stores; offer referral revenue share.
- **Content marketing (Japanese)** — guides: "How to sell Japanese cosmetics to US buyers — sample English product descriptions" — SEO to capture merchants researching cross-border.
- **Paid ads** — Google JP + Facebook targeting Shopify merchants, e-commerce managers.
- **Webinars & Shopify Meetups** — run Japan-language webinars showing before/after product pages + visual pipeline demos.
- **LINE marketing & partnerships** — co-market with LINE integration partners once LINE integration ships.

### Conversion levers

- 7-day free trial with lifetime free tier (10 products, 3 missions, 5 images) — instant productized demo.
- Case studies with measurable KPIs (AOV increase, time saved) — capture testimonials.
- Onboarding flow: Brand Soul wizard → bulk test on products → one-click publish.
- Admin UI Action extension: merchants discover AI rewriting directly from their product detail page.

## 10) Onboarding & User Experience (to reduce churn)

- **First run:** Brand Soul wizard guides merchant through brand archetype, tone, and core pillars. Dashboard shows usage stats and quick-action cards.
- **Product rewriting:** merchant selects products → show "before/after" multilingual page with tone options across 12+ locales.
- **Craftsmanship glossary:** built-in Japanese traditional craft terms automatically recognized and preserved.
- **Visual pipeline demo:** show AI-generated product images (background removal → styled background → marketing typography).
- **Reporting:** show usage metrics, credits remaining, and agent mission history.

## 11) Key Metrics & OKRs (first 12 months)

- **Acquisition:** installs → trial starts; target 500 installs by month 6.
- **Conversion:** trial → paid = 8–12% (benchmark for useful apps).
- **Churn:** keep monthly churn <6% (aim 3–4%).
- **ARPU:** $40–$80 (~¥6,000–¥12,000).
- **Unit economics:** CAC payback <6 months.
- **Support:** time to first response <24 hours, NPS target >40.

## 12) Team, Hiring & Outsourcing Plan

- **Founders (0–2):** product + lead dev (sponsor), merchant relations (sales/partnership).
- **Early hires (months 3–9):** 1 backend dev, 1 frontend dev, 1 customer success (Japanese). Outsource: LINE integration / marketplace CSV specialist if needed.
- **Month 9+:** growth marketer, data engineer (analytics), support escalation.

## 13) Implementation Timeline (90 / 180 / 365 days)

### 0–30 days: (COMPLETED)
Product spec, MVP features, dev store setup, AI prompts for JA→EN, Shopify OAuth & product fetch, initial billing flow.

### 30–90 days: (COMPLETED)
Full product rewriter (12+ locales), SEO optimizer, Price Scout, Marketing Studio, Visual Pipeline, Brand Soul system, multi-agent missions, 4-tier billing, SuperAdmin portal, lifecycle emails, GDPR compliance, i18n UI, Shopify Admin UI extension.

### 90–180 days: (CURRENT PHASE)
Launch public beta, invest in content/partners, collect merchant feedback, optimize AI costs, pursue App Store featuring, reach 100+ paying merchants.

### 180–365 days:
Add LINE integration, social publishing automation, marketplace export templates, translation memory & editable glossary, sign 3–5 agency partners, hit 300+ paying merchants target.

## 14) Risks & Mitigations

- **Translation quality dissatisfaction** → Mitigation: Brand Soul for voice consistency, craftsmanship glossary, allow human edit, "regenerate" options, user corrections feed back into agent learning.
- **AI cost blowout** → Mitigation: $150 per-shop fair-use cost cap, degraded model throttling, tiered image credits, caching, usage tiers.
- **Image generation costs** → Mitigation: image credits gated by plan tier (0/10/100 per month), fal.ai cost monitoring.
- **Shopify policy or billing changes** → Mitigation: architect to separate billing if required, maintain good partner relations with Shopify JP.
- **Competitive players (global translation apps)** → Mitigation: Japan-first UX with craftsmanship glossary, Brand Soul differentiation, visual pipeline, competitive pricing analysis, agentic missions — significantly broader feature set than translation-only tools.

## 15) Example 12-month Financial Projection (simple)

- **Month 0–3:** focus on dev, 10 pilot stores (0 revenue). ← COMPLETED
- **Month 4–6:** public beta, 50 paying merchants, revenue ¥225k–¥450k/mo.
- **Month 7–12:** growth to 300 paying merchants (target), revenue ¥2,700k/mo → annualized ≈ ¥32.4M.

## 16) Immediate Next Steps (actionable 7-day checklist)

1. Finalize App Store listing (JP + EN) with emphasis on visual pipeline + before/after demos.
2. Prepare 3 high-quality case studies with before/after product pages across different verticals (cosmetics, craft, home goods).
3. Run 5 pilot demos with real merchants — record metrics (time saved, quality ratings).
4. Optimize landing page (3D experience) for conversion with clear CTA to install.
5. Set up analytics to track install → trial → paid funnel.
6. Begin outreach to Shopify JP partner agencies for referral partnerships.

## 17) Sources / Evidence

- Shopify Japan case studies / examples (Nissin Foods and many others) — demonstrates merchants use Shopify to scale D2C & export.
- Store trackers showing ~30k–42k live Shopify stores in Japan (2025 trackers). Useful for market sizing.
- LINE ↔ Shopify integration articles & app listings — shows LINE is an important local channel (future integration target).
- Weglot & translation app presence on Shopify App Store — proves demand for store translation tools exists.
