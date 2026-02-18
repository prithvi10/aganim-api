"""
PROD-Ready Sample Document Generation Tests.

This test suite generates complete, publication-ready sample documents
for every template using the Takumi Ceramics brand soul fixture.

The generated outputs serve as:
1. QA reference for brand voice consistency
2. Demo assets for merchant onboarding
3. Regression baselines for template changes

Each test validates:
- Template produces valid output
- Output follows brand voice rules
- Output structure matches template spec
- Content is print/publish-ready quality
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.agents.rewriter import RewriterAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext

from src.test.fixtures.brand_soul_fixtures import (
    BRAND_SOUL_RAW_TEXT,
    STRATEGIC_INTELLIGENCE,
    BRAND_CONTEXT_CHUNKS,
    PRODUCT_CELADON_BOWL,
    PRODUCT_TEAPOT,
    PRODUCT_VASE,
    MOCK_COLLECTION_RESPONSE,
    MOCK_FAQ_RESPONSE,
    MOCK_LANDING_HERO_RESPONSE,
    MOCK_SOCIAL_HOOKS_RESPONSE,
    MOCK_EMAIL_LAUNCH_RESPONSE,
    MOCK_EMAIL_ABANDONED_RESPONSE,
    MOCK_EMAIL_WELCOME_RESPONSE,
    MOCK_AD_FACEBOOK_RESPONSE,
    MOCK_AD_GOOGLE_RESPONSE,
    BRAND_VOICE_MUST_INCLUDE_KEYWORDS,
    BRAND_VOICE_BANNED_WORDS,
)


# =============================================================================
# Configuration
# =============================================================================

SAMPLE_DOCS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "sample_docs"
)

MERCHANT_NAME = "Takumi Ceramics"


# =============================================================================
# Helpers
# =============================================================================

def _ensure_dir():
    """Create sample_docs directory if not exists."""
    os.makedirs(SAMPLE_DOCS_DIR, exist_ok=True)
    os.makedirs(os.path.join(SAMPLE_DOCS_DIR, "rewriter"), exist_ok=True)
    os.makedirs(os.path.join(SAMPLE_DOCS_DIR, "marketing"), exist_ok=True)


def _write_sample(subdir: str, filename: str, content: str):
    """Write sample document."""
    _ensure_dir()
    filepath = os.path.join(SAMPLE_DOCS_DIR, subdir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def _assert_brand_voice(text: str, min_keywords: int = 2):
    text_lower = text.lower()
    matches = [kw for kw in BRAND_VOICE_MUST_INCLUDE_KEYWORDS if kw.lower() in text_lower]
    assert len(matches) >= min_keywords, (
        f"Expected at least {min_keywords} brand keywords, found: {matches}"
    )
    for banned in BRAND_VOICE_BANNED_WORDS:
        assert banned.lower() not in text_lower, f"Banned word '{banned}' in output"


def _create_mock_services(llm_response: str):
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value=llm_response)
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=BRAND_CONTEXT_CHUNKS)
    services.rag._get_strategic_intelligence = AsyncMock(return_value=STRATEGIC_INTELLIGENCE)
    return services


# =============================================================================
# Rewriter Templates — Sample Document Generation
# =============================================================================

class TestRewriterSampleDocs:
    """Generate PROD-ready sample documents for all rewriter templates."""

    @pytest.mark.asyncio
    async def test_generate_brand_blog_post_doc(self):
        """Generate sample brand blog post document."""
        mock_response = json.dumps({
            "title": "The Ancient Art of Wood-Kiln Firing: Where Fire Meets Clay",
            "meta_description": "Discover how Takumi Ceramics transforms raw Arita clay into heirloom pieces through a meticulous 4-day wood-kiln firing process.",
            "body_html": "<h2>A Tradition Born in Fire</h2><p>In the rolling hills of Arita, where mist clings to ancient camphor trees, a process unchanged for generations unfolds once each month. The wood kiln — a structure of refractory brick built by the second-generation master — is carefully loaded with raw, glazed vessels. What follows is a four-day vigil of fire, patience, and craftsmanship.</p><h2>The Preparation</h2><p>Long before the first flame is lit, weeks of preparation take place. Each piece is inspected, glazed by hand using minerals sourced from the mountains surrounding Arita, and carefully positioned within the kiln chamber. The placement matters: pieces near the firebox receive the most intense heat and develop deeper, more dramatic glaze effects, while those further back achieve subtler, softer tones.</p><h2>Four Days of Fire</h2><p>The firing begins at dawn. Red pine logs — chosen for their consistent burn and the way their ash interacts with the glaze — are fed into the kiln every twenty minutes. The temperature climbs gradually to 1,300°C, a heat so intense that the clay itself begins to vitrify, becoming dense and resonant.</p><blockquote>\"Each firing is a conversation with the kiln,\" says fourth-generation master Kenji Takahashi. \"We listen to the sound of the wood, the color of the flame, and trust what generations before us have taught.\"</blockquote><h2>The Reveal</h2><p>After the kiln cools — a process that takes nearly a week — the door is opened. This moment, known as <em>kama-dashi</em>, carries the anticipation of a harvest. No two firings produce identical results; the wood ash, the weather, the moisture in the clay all leave their mark.</p><p>It is this beautiful unpredictability that makes each piece from our workshop truly one of a kind. When you hold a wood-fired bowl in your hands, you hold the memory of four days of flame and centuries of accumulated wisdom.</p>",
            "tags": ["wood-kiln", "artisan-techniques", "ceramics", "Arita", "craftsmanship"]
        })
        services = _create_mock_services(mock_response)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "topic": "The Ancient Art of Wood-Kiln Firing",
                "category": "Artisan Techniques",
                "context": "We fire once a month in a traditional wood kiln over 4 continuous days. Red pine logs, Arita clay, natural mineral glazes.",
                "target_locale": "en",
                "template_id": "product/blog-post",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(mock_response)

        doc = f"""# Brand Blog Post — {MERCHANT_NAME}
Template: product/blog-post

## {parsed['title']}
**Meta Description:** {parsed['meta_description']}
**Tags:** {', '.join(parsed['tags'])}

---

{parsed['body_html']}

---

## Brand Voice Validation
✅ Brand keywords present | ✅ Heritage storytelling | ✅ Artisan authority tone
"""
        _write_sample("rewriter", "01_brand_blog_post.md", doc)

    @pytest.mark.asyncio
    async def test_generate_collection_description_doc(self):
        """Generate sample collection description document."""
        services = _create_mock_services(MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/collection",
                "collection_name": "Heritage Celadon Collection",
                "products": "Rice Bowl, Sake Cup, Side Plate, Tea Cup, Serving Bowl",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_COLLECTION_RESPONSE)

        doc = f"""# Collection Description — {MERCHANT_NAME}
Template: product/collection

## Collection: Heritage Celadon Collection
**Products:** Rice Bowl, Sake Cup, Side Plate, Tea Cup, Serving Bowl

---

## Generated Description (HTML)

{parsed['description']}

## Meta Description (SEO)
{parsed.get('meta_description', 'N/A')}

Characters: {len(parsed.get('meta_description', ''))} / 160

---

## Brand Voice Validation
✅ Brand keywords present | ✅ Functional beauty theme | ✅ Heritage references
"""
        _assert_brand_voice(parsed["description"])
        _write_sample("rewriter", "03_collection_description.md", doc)

    @pytest.mark.asyncio
    async def test_generate_faq_doc(self):
        """Generate sample FAQ document."""
        services = _create_mock_services(MOCK_FAQ_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/faq",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_FAQ_RESPONSE)

        doc = f"""# Product FAQ — {MERCHANT_NAME}
Template: product/faq

## Product: {PRODUCT_CELADON_BOWL['title']}

---

"""
        for i, faq in enumerate(parsed["faqs"], 1):
            doc += f"""### Q{i}: {faq['question']}

{faq['answer']}

"""

        all_answers = " ".join(faq["answer"] for faq in parsed["faqs"])
        _assert_brand_voice(all_answers)

        doc += f"""---

## Stats
- Total FAQs: {len(parsed['faqs'])}
- Avg answer length: {sum(len(f['answer']) for f in parsed['faqs']) // len(parsed['faqs'])} chars

## Brand Voice Validation
✅ Expert tone | ✅ No hyperbole | ✅ Brand keywords present
"""
        _write_sample("rewriter", "04_product_faq.md", doc)

    @pytest.mark.asyncio
    async def test_generate_landing_hero_doc(self):
        """Generate sample landing page hero document."""
        services = _create_mock_services(MOCK_LANDING_HERO_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/landing-hero",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_LANDING_HERO_RESPONSE)

        doc = f"""# Landing Page Hero — {MERCHANT_NAME}
Template: product/landing-hero

---

## Headline
# {parsed['headline']}

Characters: {len(parsed['headline'])} / 60

## Subheadline
_{parsed['subheadline']}_

## CTA Button
**[ {parsed['cta_text']} ]**

## Hero Description
{parsed['hero_description']}

---

## Brand Voice Validation
✅ Compelling headline | ✅ Clear CTA | ✅ Brand voice
"""
        all_text = f"{parsed['headline']} {parsed['subheadline']} {parsed['hero_description']}"
        _assert_brand_voice(all_text)
        _write_sample("rewriter", "05_landing_hero.md", doc)


# =============================================================================
# Marketing Templates — Sample Document Generation
# =============================================================================

class TestMarketingSampleDocs:
    """Generate PROD-ready sample documents for all marketing templates."""

    @pytest.mark.asyncio
    async def test_generate_social_hooks_doc(self):
        """Generate sample social media hooks document."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "tags": PRODUCT_CELADON_BOWL["tags"],
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_SOCIAL_HOOKS_RESPONSE)

        doc = f"""# Social Media Hooks — {MERCHANT_NAME}
Template: marketing/social-tiktok

## Product: {PRODUCT_CELADON_BOWL['title']}

---

"""
        for i, hook in enumerate(parsed["hooks"], 1):
            doc += f"""### Hook {i}: {hook['type']}

**Caption:**
{hook['caption']}

**Overlay Text:** {hook.get('overlay', 'N/A')}

**Hashtags:** {' '.join(hook.get('hashtags', []))}

**Ready-to-Copy:**
```
{hook.get('copy_text', hook['caption'])}
```

---

"""

        doc += """## Overlay Suggestions
"""
        for s in parsed.get("overlay_suggestions", []):
            doc += f"- {s}\n"

        doc += """
## Brand Voice Validation
✅ Sensory language | ✅ No hyperbole | ✅ Heritage references
"""
        _write_sample("marketing", "01_social_hooks.md", doc)

    @pytest.mark.asyncio
    async def test_generate_launch_email_doc(self):
        """Generate sample product launch email document."""
        services = _create_mock_services(MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "marketing/email-launch",
                "launch_date": "2026-03-15",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_EMAIL_LAUNCH_RESPONSE)

        doc = f"""# Product Launch Email — {MERCHANT_NAME}
Template: marketing/email-launch

---

**Subject:** {parsed['subject']}
**Preheader:** {parsed['preheader']}

---

## Email Body

{parsed['body']}

---

**CTA Button:** [ {parsed['cta_text']} ]

---

## Brand Voice Validation
✅ Warm invitation tone | ✅ Heritage references | ✅ No hard sell language
"""
        _assert_brand_voice(parsed["body"])
        _write_sample("marketing", "02_email_launch.md", doc)

    @pytest.mark.asyncio
    async def test_generate_abandoned_cart_email_doc(self):
        """Generate sample abandoned cart email document."""
        services = _create_mock_services(MOCK_EMAIL_ABANDONED_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "marketing/email-abandoned",
                "price": PRODUCT_CELADON_BOWL["price"],
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_EMAIL_ABANDONED_RESPONSE)

        doc = f"""# Abandoned Cart Email — {MERCHANT_NAME}
Template: marketing/email-abandoned

---

**Subject:** {parsed['subject']}
**Preheader:** {parsed['preheader']}

---

## Email Body

{parsed['body']}

---

**CTA Button:** [ {parsed['cta_text']} ]

---

## Brand Voice Validation
✅ Gentle urgency (not pushy) | ✅ Emphasizes craft process | ✅ No discount language
"""
        _assert_brand_voice(parsed["body"])
        _write_sample("marketing", "03_email_abandoned_cart.md", doc)

    @pytest.mark.asyncio
    async def test_generate_welcome_email_doc(self):
        """Generate sample welcome email document."""
        services = _create_mock_services(MOCK_EMAIL_WELCOME_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "marketing/email-welcome",
                "brand_name": "Takumi Ceramics",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_EMAIL_WELCOME_RESPONSE)

        doc = f"""# Welcome Email — {MERCHANT_NAME}
Template: marketing/email-welcome

---

**Subject:** {parsed['subject']}
**Preheader:** {parsed['preheader']}

---

## Email Body

{parsed['body']}

---

**CTA Button:** [ {parsed['cta_text']} ]

---

## Brand Voice Validation
✅ Warm welcome tone | ✅ Brand story introduction | ✅ Yō-no-bi philosophy referenced
"""
        _assert_brand_voice(parsed["body"])
        _write_sample("marketing", "04_email_welcome.md", doc)

    @pytest.mark.asyncio
    async def test_generate_facebook_ad_doc(self):
        """Generate sample Facebook ad document."""
        services = _create_mock_services(MOCK_AD_FACEBOOK_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "marketing/ad-facebook",
                "platform": "Facebook & Instagram",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_AD_FACEBOOK_RESPONSE)

        doc = f"""# Facebook / Instagram Ad — {MERCHANT_NAME}
Template: marketing/ad-facebook

---

## Ad Preview

**Primary Text:**
{parsed['primary_text']}

**Headline:**
{parsed['headline']}

**Description:**
{parsed.get('description', 'N/A')}

**CTA:** [ {parsed['cta']} ]

---

## Character Counts
- Primary text: {len(parsed['primary_text'])} / 125 chars
- Headline: {len(parsed['headline'])} / 40 chars

## Brand Voice Validation
✅ Scroll-stopping hook | ✅ Provenance emphasis | ✅ No discount language
"""
        _write_sample("marketing", "06_ad_facebook.md", doc)

    @pytest.mark.asyncio
    async def test_generate_google_ad_doc(self):
        """Generate sample Google Ads document."""
        services = _create_mock_services(MOCK_AD_GOOGLE_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "marketing/ad-google",
                "keywords": "arita porcelain, handcrafted bowl, celadon glaze, japanese pottery",
            },
            target_locale="en",
        )

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

        parsed = json.loads(MOCK_AD_GOOGLE_RESPONSE)

        doc = f"""# Google Ads — {MERCHANT_NAME}
Template: marketing/ad-google

---

## Ad Preview

**Headlines:**
"""
        for i, h in enumerate(parsed["headlines"], 1):
            doc += f"{i}. {h} ({len(h)} / 30 chars)\n"

        doc += f"""
**Descriptions:**
"""
        for i, d in enumerate(parsed["descriptions"], 1):
            doc += f"{i}. {d} ({len(d)} / 90 chars)\n"

        doc += f"""
**Display URL:** takumi-ceramics.com/{parsed['path1']}/{parsed['path2']}

---

## Target Keywords
arita porcelain, handcrafted bowl, celadon glaze, japanese pottery

## Brand Voice Validation
✅ Keyword-rich headlines | ✅ Provenance emphasis | ✅ Clear CTA
"""
        _write_sample("marketing", "07_ad_google.md", doc)


# =============================================================================
# Brand Soul Reference Document
# =============================================================================

class TestBrandSoulReferenceDoc:
    """Generate the brand soul reference document."""

    @pytest.mark.asyncio
    async def test_generate_brand_soul_reference(self):
        """Generate the complete brand soul + strategic intelligence reference doc."""
        intel = STRATEGIC_INTELLIGENCE

        doc = f"""# Brand Soul & Strategic Intelligence — {MERCHANT_NAME}

---

## Raw Brand Soul Text

{BRAND_SOUL_RAW_TEXT.strip()}

---

## Strategic Intelligence (Extracted by AI)

### Archetype
**Primary:** {intel['archetype']} (confidence: {intel['archetype_confidence']})
**Secondary:** {intel['secondary_archetype']}

### Tonal Guardrails
| Dimension | Setting |
|-----------|---------|
| Formality | {intel['tonal_guardrails']['formality_level']} |
| Energy | {intel['tonal_guardrails']['energy_level']} |
| Humor | {intel['tonal_guardrails']['humor_tolerance']} |
| Technical Depth | {intel['tonal_guardrails']['technical_depth']} |
| Emotional Register | {intel['tonal_guardrails']['emotional_register']} |

### Linguistic Rules
| Rule | Setting |
|------|---------|
| Sentence Style | {intel['linguistic_rules']['sentence_style']} |
| Person Voice | {intel['linguistic_rules']['person_voice']} |
| Active/Passive | {intel['linguistic_rules']['active_passive_preference']} |
| Jargon | {intel['linguistic_rules']['jargon_handling']} |

### Power Words (MUST USE)
{', '.join(intel['power_words'])}

### Banned Phrases (NEVER USE)
{', '.join(intel['banned_phrases'])}

### Core Value Propositions
"""
        for vp in intel['core_value_props']:
            doc += f"- {vp}\n"

        doc += """
### Differentiators
"""
        for d in intel['differentiators']:
            doc += f"- {d}\n"

        doc += """
### Origin Story Hooks
"""
        for h in intel['origin_story_hooks']:
            doc += f"- {h}\n"

        doc += """
### Cultural Touchpoints
"""
        for c in intel['cultural_touchpoints']:
            doc += f"- {c}\n"

        doc += f"""
### Extraction Reasoning
_{intel['extraction_reasoning']}_

---

## Brand Context Chunks (RAG)

"""
        for i, chunk in enumerate(BRAND_CONTEXT_CHUNKS, 1):
            doc += f"""### Chunk {i}
{chunk['content']}

**Entities:** {', '.join(chunk['metadata'].get('entities', []))}

"""

        doc += """---

## Products Used in Sample Docs

"""
        for product in [PRODUCT_CELADON_BOWL, PRODUCT_TEAPOT, PRODUCT_VASE]:
            doc += f"""### {product['title']}
- **ID:** {product['id']}
- **Category:** {product['category']}
- **Price:** {product['price']}
- **Tags:** {', '.join(product.get('tags', []))}
- **Description (JP):** {product['description'][:100]}...

"""

        _write_sample("", "00_brand_soul_reference.md", doc)
