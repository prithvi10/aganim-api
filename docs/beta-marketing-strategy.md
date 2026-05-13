# Aganim AI — Closed Beta Marketing Strategy

> **Goal:** Acquire 10–50 Japanese Shopify merchants for a free private beta, collect structured feedback, fix issues, and build testimonials before public launch.

> **Constraint:** No revenue collection during beta (VISA situation). All access is free with enhanced credits.

> **Infrastructure:** Google Workspace available — used as the operational backbone for the entire beta program.

---

## Google Workspace as Beta Operations Hub

Google Workspace replaces the need for multiple paid SaaS tools. Every stage of the beta — signup, outreach, onboarding, feedback, tracking, and reporting — runs through it.

### Workspace Setup

Create these assets on Day 1:

| Asset | Google Tool | Purpose |
|-------|-------------|---------|
| **Beta Signup Form** | Google Forms | Collect merchant applications (replaces Typeform) |
| **Feedback Survey** | Google Forms | Structured Day 7/14/30 surveys |
| **Beta Tracker** | Google Sheets | Master CRM — every merchant, their status, usage, feedback scores |
| **Outreach Log** | Google Sheets | Track every cold email sent, open status, reply status |
| **Bug & Issue Board** | Google Sheets | Triage issues from ConcernLog + community + forms |
| **Case Study Docs** | Google Docs | Before/after write-ups per merchant for App Store listing |
| **Beta Assets Folder** | Google Drive | Screenshots, demo videos, outreach templates, brand assets |
| **Onboarding Calls** | Google Meet | Unlimited duration (no 40-min Zoom limit) |
| **Onboarding Calendar** | Google Calendar | Booking page for merchants to self-schedule onboarding |
| **Beta Comms Group** | Google Groups | `beta@aganim-ai.com` mailing list for announcements |
| **Beta Landing Page** | Google Sites | Free public-facing signup page at a custom URL |
| **Professional Outreach** | Gmail (Workspace) | Send from `hello@aganim-ai.com` or `beta@aganim-ai.com` |

---

### G1. Beta Signup Form (Google Forms)

Create a public form linked from your landing page, social posts, and outreach emails.

**Fields:**
1. Store URL (short text, required)
2. Contact email (short text, required)
3. Contact name (short text)
4. Product category (dropdown: Cosmetics, Craft/Artisan, Food & Beverage, Fashion, Home Goods, Electronics, Other)
5. Primary target market (checkboxes: US, EU, Southeast Asia, Korea, Taiwan/China, Other)
6. Monthly product count (dropdown: 1–50, 51–200, 201–500, 500+)
7. "What's your biggest cross-border pain point?" (long text)
8. "How do you currently translate product pages?" (dropdown: Manually, Freelancer, Agency, Machine translation, Don't translate yet)
9. How did you hear about Aganim? (dropdown: Twitter, Reddit, Shopify Community, Facebook, LinkedIn, Friend/Referral, Other)

**Form settings:**
- Response destination → linked to the **Beta Tracker** Google Sheet automatically
- Enable email notifications on each submission so you can respond within hours
- Add a confirmation message: "Thanks for applying! We'll email you within 24 hours with setup instructions."

---

### G2. Beta Tracker — Master CRM (Google Sheets)

Single sheet with tabs that becomes your command center.

**Tab 1: Merchant Pipeline**

| Column | Content |
|--------|---------|
| Store URL | From signup form (auto-populated) |
| Email | From signup form |
| Name | From signup form |
| Category | From signup form |
| Target Market | From signup form |
| Source | How they found you |
| Signup Date | Auto-timestamp from form |
| Status | `applied` → `invited` → `installed` → `onboarded` → `active` → `churned` |
| Onboarding Date | When the call happened |
| Plan Granted | Free / Standard / Pro |
| Products Rewritten | Pull from SuperAdmin (update weekly) |
| Features Used | Pull from SuperAdmin |
| Feedback Score | From feedback form |
| Willingness to Pay | From feedback form |
| Testimonial | Yes/No + quote text |
| Notes | Free-form observations |

**Tab 2: Outreach Tracker**

| Column | Content |
|--------|---------|
| Store URL | Target store |
| Email | Contact email |
| Date Sent | When outreach was sent |
| Channel | Cold email / Twitter DM / Reddit / etc. |
| Template Used | EN / JP |
| Reply | Yes / No / Bounced |
| Outcome | Signed up / Not interested / No reply |
| Follow-up Date | When to follow up |

**Tab 3: Feedback Aggregation**

Auto-populated from feedback Google Form responses. Add computed columns:
- Average satisfaction score
- Feature usage distribution (pivot)
- Willingness-to-pay breakdown
- Common pain points (tag manually)

**Tab 4: Bug & Issue Tracker**

| Column | Content |
|--------|---------|
| ID | Auto-increment |
| Date | When reported |
| Merchant | Store domain |
| Source | ConcernLog / Form / Slack / Call |
| Category | Bug / UX / Translation Quality / Performance / Feature Request |
| Severity | Critical / High / Medium / Low |
| Description | What happened |
| Status | `open` → `in_progress` → `fixed` → `verified` |
| Fix Date | When resolved |
| Notes | Resolution details |

---

### G3. Professional Outreach via Gmail (Workspace)

Your Workspace gives you a branded email domain. Send all outreach from a professional address instead of a personal Gmail.

**Recommended setup:**
- `hello@aganim-ai.com` — primary outreach and merchant communication
- `beta@aganim-ai.com` — beta program announcements (via Google Groups)
- `support@aganim-ai.com` — support alias (forwards to your inbox)

**Gmail outreach advantages over SES:**
- Personal threading — merchants see a real inbox they can reply to naturally
- Better deliverability for cold outreach (SES is better for transactional/bulk)
- Gmail templates (canned responses) for quick personalized replies
- Schedule Send for optimal timing (send at 10 AM JST regardless of when you write)
- Track conversations per merchant in-thread

**Workflow:** Use Gmail for all 1-to-1 outreach and relationship emails. Keep SES for automated lifecycle emails (welcome, feedback requests, bulk announcements).

---

### G4. Google Calendar — Self-Service Onboarding Booking

Set up a Google Calendar appointment schedule (built-in feature, no Calendly needed):

1. Go to Google Calendar → Create appointment schedule
2. Set available slots: e.g., Mon–Fri, 10:00–12:00 and 14:00–16:00 JST
3. Duration: 20 minutes
4. Buffer: 10 minutes between calls
5. Add Google Meet link automatically
6. Share the booking page URL in your beta welcome email

**Welcome email template (sent after signup approval):**

> Subject: Welcome to the Aganim AI Beta — let's set up your store
>
> Hi [Name],
>
> Welcome to the Aganim AI private beta! You now have full access to all features — no limits, no charge.
>
> **Next step:** Book a 15-minute onboarding call so I can set up Brand Soul for your store and show you the best features for your products.
>
> 📅 Book your slot: [Google Calendar booking link]
>
> If you prefer to explore on your own, here's your install link:
> [Direct Shopify install URL]
>
> Talk soon,
> [Your name]

---

### G5. Google Meet — Onboarding & Exit Interviews

Use Google Meet (included in Workspace) instead of Zoom:
- **No time limit** (Zoom free caps at 40 min)
- Auto-records to Google Drive (ask permission first)
- Transcription available — review merchant feedback without rewatching
- Share screen to walk through the app live

**Recording strategy:** Record onboarding calls (with merchant permission). Transcribe key quotes for testimonials and case studies. Store recordings in the shared Drive folder.

---

### G6. Google Groups — Beta Mailing List

Create a Google Group: `beta-testers@aganim-ai.com`

- Add all beta merchants as members
- Use for weekly announcements, changelog updates, survey reminders
- Merchants can reply to discuss — creates a lightweight forum without Slack/Discord setup friction
- Archive serves as a searchable record of all beta communications

**Alternative to Slack/Discord:** For Japanese merchants who may not use Slack/Discord daily, a Google Group email list has higher open rates. Everyone checks email; not everyone checks Slack.

---

### G7. Google Sites — Free Beta Landing Page

Build a one-page site at `sites.google.com/aganim-ai.com/beta` (or map to a custom subdomain like `beta.aganim-ai.com`):

**Page structure:**
1. Hero: "Aganim AI Private Beta — Free Access for Japanese Shopify Merchants"
2. Problem statement: "Selling Japanese products overseas shouldn't require hiring translators"
3. 3 feature highlights with screenshots (Rewriter, SEO, Visual Pipeline)
4. Before/After product page example
5. "What you get": Full access to all features, zero cost, direct support from the founder
6. Embedded Google Form for signup
7. FAQ: "How long is the beta?", "Will I have to pay later?", "What do you need from me?"

**Advantages:** Free, instant, indexed by Google, professional enough for a beta signup page, no coding required.

---

### G8. Google Drive — Shared Assets Folder

Folder structure:

```
Aganim Beta/
├── Outreach Templates/
│   ├── cold-email-english.md
│   ├── cold-email-japanese.md
│   ├── twitter-posts.md
│   └── forum-posts.md
├── Demo Assets/
│   ├── before-after-screenshots/
│   ├── feature-demo-gifs/
│   └── product-page-examples/
├── Merchant Recordings/
│   ├── onboarding-calls/
│   └── exit-interviews/
├── Case Studies/
│   ├── merchant-1-cosmetics.gdoc
│   ├── merchant-2-crafts.gdoc
│   └── template.gdoc
├── Feedback Data/
│   └── (auto-linked from Google Forms)
└── Brand Assets/
    ├── aganim-logo.png
    ├── app-screenshots/
    └── social-media-banners/
```

---

### G9. Google Sheets — Weekly Dashboard

Create a summary dashboard sheet (fed from the other tabs/forms) with these live metrics:

| Metric | Formula/Source | Target |
|--------|----------------|--------|
| Total signups | `COUNTA` from signup form responses | 50+ |
| Installed | Count where status ≠ `applied` | 30+ |
| Onboarded (had call) | Count where Onboarding Date filled | 25+ |
| Active (used in last 7 days) | Manual update from SuperAdmin | 20+ |
| Avg satisfaction score | `AVERAGE` from feedback form | > 4.0 |
| Willingness to pay (% Yes) | `COUNTIF` from feedback form | > 50% |
| Testimonials collected | Count where Testimonial = "Yes" | 5+ |
| Open bugs (Critical/High) | `COUNTIFS` from bug tracker | < 5 |
| Outreach emails sent | `COUNTA` from outreach tracker | 100+ |
| Reply rate | Replies / Sent | > 15% |

---

## Phase 1: Prepare the Product for Beta (Days 1–3)

### 1.1 Boost Free Tier for Beta Testers

Current Free tier (10 products / 3 missions / 5 images lifetime) is too restrictive for meaningful feedback. Options:

| Approach | How | Effort |
|----------|-----|--------|
| **Manual upgrade** | Set beta merchants to `Standard` plan in DB via SuperAdmin portal (bypasses Shopify Billing) | Zero code change |
| **Promo flag** | Use existing `PROMO_PRICING_ENABLED` to unlock enhanced entitlements for all installs during beta | Config change only |
| **Allowlist boost** | Add a `beta_tester` flag to Shop model; grant Standard-equivalent limits when true | Small code change |

**Recommended:** Manual upgrade via SuperAdmin — simplest, no code changes, full control per merchant.

### 1.2 Create a Feedback Form (Google Forms)

Link: `https://forms.gle/aganim-feedback` (already referenced in codebase)

**Questions to include:**

1. Overall satisfaction (1–5 stars)
2. Translation quality rating (1–5 stars)
3. Features used (multi-select): Rewriter, SEO Optimizer, Price Scout, Marketing Studio, Visual Pipeline, Missions, Brand Soul
4. "Which feature was most valuable to you?" (single select)
5. "What was your biggest frustration?" (open text)
6. "Would you pay $39/month for this?" (Yes / Maybe / No)
7. "What price feels fair?" ($19 / $39 / $59 / $89 / Other)
8. "What feature is missing?" (open text)
9. "How did you handle this before Aganim?" (open text)
10. Permission to use their quote as a testimonial (Yes / No)
11. Store URL (for tracking)

### 1.3 Create a Beta Signup Page

Use **Google Sites** (free with Workspace) to build a landing page. Embed the **Google Forms** signup form directly on the page. See section **G7** above for the full page structure and **G1** for form fields.

---

## Phase 2: Find Your 10–50 Merchants (Days 3–14)

### Channel Breakdown (ranked by expected conversion)

### 2.1 Direct Outreach (Highest Quality) — Target: 5–15 merchants

**Where to find merchants:**
- [Store Leads](https://storeleads.app) — filter by country: Japan, platform: Shopify (~$29/mo)
- [BuiltWith](https://builtwith.com) — find Japanese Shopify stores
- Manually browse Japanese D2C brands that sell internationally (check for English language toggle or Amazon US listings)

**Outreach template (English):**

> Subject: Free AI tool to translate your [product category] for overseas markets
>
> Hi [Name],
>
> I noticed your store [store name] — your [products] are beautiful. I'm building Aganim AI, a tool that rewrites Japanese product pages into sales-grade English (+ 11 other languages), optimizes SEO for overseas markets, and generates marketing visuals.
>
> I'm looking for 20 Japanese merchants to beta test for free — full access, no charge, no commitment. In return, I'd love your honest feedback on the translation quality.
>
> Would you be interested? I can set up your store in 5 minutes.
>
> [Your name]

**Outreach template (Japanese):**

> 件名：【無料】日本のEC商品を海外向けに自動翻訳するAIツール — ベータテスター募集
>
> [名前]様
>
> [ストア名]の商品を拝見しました。素晴らしい商品ですね。
>
> 現在、日本のShopifyストア向けに「Aganim AI」というAIツールを開発しています。日本語の商品ページを販売力のある英語（＋11言語）に書き換え、海外市場向けのSEO最適化やマーケティングビジュアルの生成も行えるツールです。
>
> 現在、20店舗のベータテスターを募集しています。完全無料・制限なし・義務なしでご利用いただけます。翻訳品質について率直なフィードバックをいただければ幸いです。
>
> ご興味があれば、5分でセットアップできます。
>
> [あなたの名前]

**Cadence:** Send 10–20 personalized emails per day via **Gmail** (Workspace) for 1-to-1 threading. Track all sends in the **Outreach Tracker** Google Sheet (see section G2).

---

### 2.2 Twitter/X — Japanese EC Community — Target: 5–20 merchants

**Hashtags to use and monitor:**
- `#Shopify` `#越境EC` `#EC運営` `#ネットショップ` `#D2C` `#海外販売`
- `#ハンドメイド` `#日本製` `#MadeInJapan` `#伝統工芸`

**Content plan (1 post/day for 2 weeks):**

| Day | Post Type | Content |
|-----|-----------|---------|
| 1 | Before/After | Screenshot: Japanese product page → English rewrite. "Built an AI that does this in 10 seconds." |
| 2 | Thread (JP) | 「越境ECの壁は翻訳じゃない。売れる英語にすること。」— explain the problem, show solution |
| 3 | Visual Pipeline | GIF/video: background removal → styled product image → marketing visual |
| 4 | Pain point | "Japanese merchants spend ¥50k/month on translators. What if AI could do it better?" |
| 5 | SEO feature | Screenshot: SERP analysis + optimized meta tags. "Your Japanese SEO doesn't work on Google US." |
| 6 | Price Scout | Screenshot: competitor pricing analysis. "Know what US competitors charge before you price." |
| 7 | Beta CTA | "Looking for 20 Japanese Shopify merchants to beta test for free. DM me or sign up: [link]" |
| 8–14 | Repeat cycle | Alternate between feature demos, merchant stories, and beta CTAs |

**Engagement:** Reply to merchants posting about cross-border problems. Offer free rewrites in DMs as a hook.

---

### 2.3 Shopify Community Forums — Target: 5–15 merchants

**Where to post:**
- [Shopify Community — Japan](https://community.shopify.com/) (Japanese section)
- [Shopify Community — Apps & Tools](https://community.shopify.com/c/apps-and-tools/ct-p/apps-tools)
- [Shopify Community — Store Feedback](https://community.shopify.com/c/store-feedback/ct-p/store-feedback)

**Post template:**

> **Title:** [Free Beta] AI tool that rewrites Japanese product pages for global markets
>
> Hi everyone! I'm building Aganim AI — an app specifically for Japanese Shopify merchants who want to sell overseas.
>
> What it does:
> - Rewrites product descriptions from Japanese to 12+ languages (not literal translation — marketing-grade copy)
> - SEO optimization with SERP analysis for target markets
> - Competitor price analysis (Google Shopping data)
> - Marketing content: social hooks, ad copy, email templates
> - AI-generated product images (background removal + styled visuals)
>
> I'm looking for 20 beta testers. Full access, completely free, no strings attached. I just need your honest feedback.
>
> Sign up here: [link]
>
> Happy to answer any questions!

---

### 2.4 Reddit — Target: 3–10 merchants

**Subreddits:**
- r/shopify (~200k members)
- r/ecommerce (~120k members)
- r/Entrepreneur (~2M members)
- r/japanlife (for English-speaking merchants in Japan)
- r/FulfillmentByAmazon (merchants selling internationally)

**Post approach:** Value-first. Share a before/after example as an image post, mention beta in comments. Reddit hates direct promotion — lead with the problem and solution, not the pitch.

---

### 2.5 Facebook Groups — Target: 5–15 merchants

**Groups to join:**
- Shopify Japan (JP)
- 越境EC・海外販売 (JP)
- ネットショップ運営 (JP)
- Shopify Entrepreneurs (EN)
- Ecommerce Entrepreneurs (EN)
- Shopify App Developers & Merchants (EN)

**Approach:** Post a before/after product page image. Ask a question first ("Anyone selling Japanese products overseas? What's your biggest challenge?"), then offer the beta in replies.

---

### 2.6 LinkedIn — Target: 3–10 merchants

- Post your indie founder story: "I'm building AI to help Japanese craftsmen sell globally"
- Connect with: Shopify agency owners in Japan, e-commerce consultants, cross-border logistics companies
- Comment on posts about Japanese e-commerce, cross-border trade, Shopify
- The "founder building in public" narrative resonates strongly on LinkedIn

---

### 2.7 Product Hunt & Indie Hackers — Target: 3–10 merchants

- **Indie Hackers:** Post as "Show IH" — the maker community gives great feedback
- **Product Hunt:** Add to "Upcoming" products. Save the full launch for post-beta
- **Hacker News:** "Show HN" post if you can frame it as technically interesting (multi-agent AI architecture)

---

### 2.8 Japanese Content Platforms — Target: 3–10 merchants

- **note.com** — Write an article in Japanese about the cross-border problem and your AI approach
- **Qiita** — Technical article about the AI/agent architecture (attracts technical founders who also run stores)
- **Zenn** — Similar to Qiita, developer audience

---

## Phase 3: Onboard & Activate (Days 7–21)

### 3.1 Personal Onboarding Call (Every Merchant)

**Duration:** 15–20 minutes via **Google Meet** (unlimited duration with Workspace, auto-records to Drive)

**Script:**
1. (2 min) Intro — thank them for joining, quick overview
2. (3 min) Brand Soul setup — walk through the wizard together
3. (5 min) Live demo — rewrite 3 of their actual products, show before/after
4. (3 min) Show SEO + Price Scout on one product
5. (2 min) Point them to feedback form, Google Group, concern submission in-app

**Booking:** Use **Google Calendar appointment schedule** (see section G4) — merchants self-book from a link in their welcome email. No Calendly needed.

**Recording:** Record calls (with permission) to Google Drive. Use transcripts for testimonial quotes and case study material.

### 3.2 Create a Beta Testers Community

**Primary: Google Groups** — `beta-testers@aganim-ai.com` (see section G6)
- Lowest friction for Japanese merchants (everyone checks email)
- Weekly announcements, changelog updates, survey reminders
- Merchants can reply-all to discuss — lightweight forum
- Searchable archive of all beta communications

**Optional add-on: Slack or Discord** with channels:
- `#introductions` — merchants introduce their store
- `#feedback` — real-time feedback and bug reports
- `#feature-requests` — what they want built next
- `#showcase` — merchants share their rewritten pages
- `#announcements` — your weekly updates

**Alternative:** LINE OpenChat group (since merchants are in Japan, LINE may get higher engagement for real-time chat)

### 3.3 Weekly Check-in Email

Use **Google Groups** (`beta-testers@aganim-ai.com`) for announcements + your existing SES outreach for automated lifecycle emails.

**Week 1 email:** "How's your first week? Here's a quick tip: try the SEO Optimizer on your best-selling product."

**Week 2 email:** "We'd love your feedback — please fill out this 2-minute survey: [Google Form link]"

**Week 3 email:** "Here's what we fixed based on your feedback: [changelog]. What should we tackle next?"

**Week 4 email:** "Your beta access continues! Here's your usage summary: X products rewritten, Y images generated."

---

## Phase 4: Collect Feedback & Iterate (Days 14–45)

### 4.1 Feedback Collection (Three Channels)

| Channel | What it captures | Frequency |
|---------|------------------|-----------|
| **Google Forms** | Structured ratings, willingness to pay, satisfaction | Day 7, 14, 30 |
| **Google Sheets** | Aggregated metrics, pipeline tracking, bug triage | Updated weekly |
| **ConcernLog** (in-app) | Bugs, issues, complaints with shop context | Ongoing |
| **Google Groups** | Announcements, threaded discussions, qualitative feedback | Ongoing |
| **Google Meet recordings** | Onboarding & exit interview transcripts | Per call |

### 4.2 Metrics to Track Per Merchant

Pull from your database (SuperAdmin dashboard):

| Metric | What it tells you | Target |
|--------|-------------------|--------|
| Days from install → first rewrite | Activation speed | < 1 day |
| Products rewritten (total) | Depth of usage | > 5 per merchant |
| Features used | Feature-market fit | 3+ features per merchant |
| Missions run | Advanced engagement | > 1 per merchant |
| Return visits (weekly) | Retention signal | 2+ per week |
| Concerns submitted | Pain point density | Track themes |

### 4.3 Exit Interview (Day 30)

15-minute **Google Meet** call with each active merchant (recorded to Drive with permission):

1. "What did you like most?"
2. "What almost made you stop using it?"
3. "Would you pay $39/month? $89?"
4. "Would you recommend this to another merchant?"
5. "Can I quote you for our App Store listing?"

### 4.4 Testimonial Collection

Ask every merchant who rates 4+ stars:

> "Would you mind sharing a short quote about your experience? Something like: 'Aganim helped me [specific result] in [timeframe].' We'd feature your store name on our App Store listing."

**Target:** 5+ testimonials by end of beta.

---

## Phase 5: Control Access (Keeping It Closed)

### Recommended: Unlisted App + Direct Install Link

Do NOT publish to Shopify App Store yet. Use the direct OAuth install URL:

```
https://admin.shopify.com/oauth/install?client_id=315cfaf63c9baf27e4ba9a22b91b168e
```

Only share this link with approved beta testers. This gives you:
- Full control over who installs
- No premature public reviews
- No pressure to handle scale before you're ready

### Alternative: Allowlist Gating

If you want the app listed for SEO/discoverability, add domain-based gating in the OAuth callback. Merchants not on the allowlist see a "Beta is full — join the waitlist" page.

---

## Timeline

| Day | Milestone |
|-----|-----------|
| **1–3** | Set up Google Workspace hub (Forms, Sheets tracker, Sites landing page, Calendar booking, Groups mailing list). Boost Free tier for beta. Prepare outreach templates in Drive. |
| **3–5** | Post on Twitter (JP), Shopify Community, Reddit, Facebook groups — all link to Google Sites signup page |
| **5–10** | Start direct outreach via Gmail (10–20 personalized emails/day), post on LinkedIn, Indie Hackers, note.com |
| **7–14** | Onboard first 10 merchants via Google Meet, add to Google Group, track in Sheets CRM |
| **14** | Send first feedback survey (Google Forms) via Google Groups |
| **14–21** | Iterate on top issues (tracked in Sheets bug board), continue onboarding to 30+ merchants |
| **21–30** | Second feedback survey, review Sheets dashboard metrics, continue shipping fixes |
| **30–45** | Exit interviews (Google Meet, recorded), collect testimonials, write case studies in Google Docs |
| **45+** | Fix critical issues, finalize App Store listing with testimonials, prepare for public launch |

---

## Budget

| Item | Cost | Notes |
|------|------|-------|
| Google Workspace (Forms, Sheets, Sites, Meet, Calendar, Groups, Drive, Gmail) | ¥0 | Already have access |
| Twitter / Reddit / Facebook / LinkedIn / Shopify Community posts | ¥0 | Organic only |
| Store Leads (merchant research for direct outreach) | ~$29/mo (~¥4,400) | Optional — can manually find stores for free |
| note.com / Qiita / Zenn articles | ¥0 | |
| SES outreach emails (automated lifecycle) | ~¥500/mo | Already built |
| **Total** | **¥0–¥4,900/mo** | |

Google Workspace eliminates the need for: Typeform (forms), Calendly (booking), Zoom (video calls), Notion (docs), Mailchimp (mailing list), Trello (bug tracking), and a separate landing page builder.

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Beta signups | 50+ |
| Installed & activated | 25–30 |
| Features used per merchant | 3+ |
| Feedback surveys completed | 15+ |
| Testimonials collected | 5+ |
| Willingness to pay ("Yes") | > 50% of respondents |
| Critical bugs found & fixed | Track count |
| NPS score | > 40 |

---

## Post-Beta Transition

Once you have:
- 5+ testimonials
- Top 10 bugs fixed
- 3 before/after case studies
- Confidence in willingness to pay

Then:
1. Submit app to Shopify App Store for public listing
2. Activate Shopify Billing (paid plans)
3. Convert beta merchants to paid plans (offer first month free or discounted as thanks)
4. Launch on Product Hunt
5. Begin paid acquisition (Google JP + Facebook ads)
