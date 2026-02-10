"""
Brand Soul Test Fixtures - PROD-quality test data for template testing.

Provides a rich, realistic Japanese artisan pottery brand ("Takumi Ceramics")
with brand soul text, strategic intelligence, and product data that exercises
all content templates with genuine brand voice enforcement.
"""


# =============================================================================
# Brand Soul — Raw Text (what a merchant would paste into the Brand Soul wizard)
# =============================================================================

BRAND_SOUL_RAW_TEXT = """
Takumi Ceramics — 匠陶磁器

Founded in 1923 in the heart of Arita, Saga Prefecture — the birthplace of Japanese
porcelain — Takumi Ceramics is a fourth-generation family workshop. Our founder,
Master Takumi Hideo, trained under the legendary kiln-master Sakaida Kakiemon XIV
before establishing his own atelier dedicated to the pursuit of functional beauty.

Our Philosophy: Yō-no-bi (用の美)
We believe in "the beauty of use" — that everyday objects should carry the same
reverence as museum pieces. Every cup, plate, and vase we create is designed to
be touched, used, and loved daily. We reject the idea that fine craft must be
placed behind glass.

Our Process:
Each piece passes through 23 individual steps over 6 weeks:
1. Local Amakusa clay is hand-wedged for 30 minutes to remove air pockets
2. Wheel-thrown by a single artisan (no molds, ever)
3. Bisque-fired at 900°C for 12 hours in our century-old noborigama (climbing kiln)
4. Hand-painted using natural Gosu cobalt pigments — each brushstroke unique
5. Glaze-dipped in our proprietary celadon glaze (recipe unchanged since 1923)
6. Final firing at 1300°C for 36 hours, producing the signature "jade whisper" finish

Core Pillars:
- Heritage & Authenticity: Four generations. One unbroken lineage. Zero shortcuts.
- Functional Beauty (Yō-no-bi): Made to be used, not displayed.
- Material Integrity: Amakusa clay, natural Gosu pigments, proprietary celadon glaze.
- Sustainable Craft: Zero-waste kiln cycles, rainwater clay processing, solar-powered studio.

Brand Voice:
We speak with quiet confidence — never shouting, always inviting. Our words should
feel like holding a warm cup of tea. We use sensory language (texture, warmth, weight)
but never hyperbole. "Exquisite" is fine; "the most amazing thing ever" is not.
We refer to ourselves as "we" and our customers as "you."

What We Are NOT:
- Not mass-produced. Not factory-made. Not "fast ceramics."
- We never use terms like "cheap," "bargain," "deal," or "discount."
- We don't compete on price. We compete on soul.

Target Customer:
Design-conscious homeowners aged 30-55 who appreciate Japanese aesthetics and are
willing to invest in pieces that will last generations. They shop at Muji, follow
Kinfolk magazine, and care about provenance.
"""


# =============================================================================
# Strategic Intelligence — Extracted JSON (what IntelligenceExtractorService produces)
# =============================================================================

STRATEGIC_INTELLIGENCE = {
    "archetype": "artisan_master",
    "archetype_confidence": 0.95,
    "secondary_archetype": "heritage_house",
    "tonal_guardrails": {
        "formality_level": "professional",
        "energy_level": "calm",
        "humor_tolerance": "subtle",
        "technical_depth": "enthusiast",
        "emotional_register": "trust",
    },
    "linguistic_rules": {
        "sentence_style": "flowing_narrative",
        "person_voice": "first_person_plural",
        "active_passive_preference": "active_preferred",
        "jargon_handling": "embrace",
    },
    "power_words": [
        "handcrafted",
        "heritage",
        "artisan",
        "heirloom",
        "kiln-fired",
        "provenance",
        "timeless",
        "purposeful",
        "tactile",
        "enduring",
        "soul",
        "reverence",
        "mastery",
        "lineage",
        "intentional",
    ],
    "banned_phrases": [
        "cheap",
        "bargain",
        "deal",
        "discount",
        "mass-produced",
        "factory-made",
        "fast",
        "best ever",
        "amazing",
        "incredible",
        "game-changer",
        "hack",
        "must-have",
        "OMG",
        "limited-time offer",
    ],
    "core_value_props": [
        "Fourth-generation Arita porcelain with an unbroken 100-year lineage",
        "23-step, 6-week process using century-old noborigama kiln",
        "Designed for daily use — functional beauty (Yō-no-bi) philosophy",
        "Sustainable zero-waste craft with natural materials only",
    ],
    "differentiators": [
        "Only workshop still using the original 1923 celadon glaze recipe",
        "Each piece hand-thrown by a single artisan — never molded",
        "Natural Gosu cobalt pigments for hand-painted designs",
        "Signature 'jade whisper' finish from 1300°C final firing",
    ],
    "origin_story_hooks": [
        "Founded 1923 in Arita — birthplace of Japanese porcelain",
        "Founder trained under legendary Kakiemon XIV",
        "Family workshop passed through four generations",
        "Century-old noborigama climbing kiln still in use today",
    ],
    "cultural_touchpoints": [
        "Yō-no-bi (用の美) — the beauty of use philosophy",
        "Arita porcelain tradition (400+ year heritage)",
        "Noborigama kiln culture of Saga Prefecture",
        "Wabi-sabi — beauty in imperfection and transience",
        "Japanese tea ceremony aesthetics",
    ],
    "extraction_reasoning": (
        "The brand strongly embodies the Artisan Master archetype through its emphasis on "
        "handcraftsmanship, single-artisan production, and detailed 23-step process. The "
        "Heritage House is a strong secondary archetype given the four-generation lineage "
        "and founding in 1923. The tonal guardrails reflect the brand's stated voice: "
        "'quiet confidence — never shouting, always inviting.'"
    ),
}


# =============================================================================
# Brand Context Chunks — RAG retrieval results
# =============================================================================

BRAND_CONTEXT_CHUNKS = [
    {
        "content": (
            "Takumi Ceramics is a fourth-generation family workshop founded in 1923 in Arita, "
            "Saga Prefecture. We believe in Yō-no-bi — the beauty of use — creating functional "
            "pieces meant to be touched, used, and loved daily."
        ),
        "metadata": {
            "source_type": "wizard",
            "lang": "en",
            "entities": ["region:Arita", "philosophy:Yō-no-bi", "time_period:1923"],
        },
    },
    {
        "content": (
            "Each piece passes through 23 steps over 6 weeks. Local Amakusa clay is hand-wedged, "
            "wheel-thrown by a single artisan, bisque-fired at 900°C, hand-painted with natural "
            "Gosu cobalt pigments, celadon glaze-dipped, and final-fired at 1300°C for 36 hours."
        ),
        "metadata": {
            "source_type": "wizard",
            "lang": "en",
            "entities": [
                "material:Amakusa clay",
                "material:Gosu cobalt",
                "technique:wheel-thrown",
                "technique:celadon glaze",
                "process:23-step process",
            ],
        },
    },
    {
        "content": (
            "Core Pillars: Heritage & Authenticity — four generations, one unbroken lineage, "
            "zero shortcuts. Functional Beauty (Yō-no-bi) — made to be used, not displayed. "
            "Material Integrity — Amakusa clay, Gosu pigments, proprietary celadon glaze. "
            "Sustainable Craft — zero-waste kiln cycles, rainwater clay processing."
        ),
        "metadata": {
            "source_type": "wizard",
            "lang": "en",
            "entities": [
                "philosophy:Yō-no-bi",
                "attribute:sustainable",
                "certification:zero-waste",
            ],
        },
    },
]


# =============================================================================
# Product Data — Realistic products for template testing
# =============================================================================

PRODUCT_CELADON_BOWL = {
    "id": "gid://shopify/Product/12345",
    "title": "Celadon Jade Rice Bowl — 翡翠茶碗",
    "description": (
        "手作りの青磁茶碗。天草陶石を使用し、匠の職人が一つ一つ轆轤で成形。"
        "1300°Cで36時間焼成した「翡翠のささやき」仕上げ。日常使いのための機能美。"
        "直径12cm、高さ7cm。食洗機対応。"
    ),
    "category": "Tableware",
    "tags": ["rice-bowl", "celadon", "handcrafted", "arita", "gift"],
    "price": "¥12,800",
}

PRODUCT_TEAPOT = {
    "id": "gid://shopify/Product/67890",
    "title": "Gosu Blue Side-Handle Teapot — 呉須横手急須",
    "description": (
        "呉須で手描きされた横手急須。天草陶石使用。茶こし一体型。"
        "容量350ml。お茶の旨みを最大限に引き出す内側無釉仕上げ。"
    ),
    "category": "Tea Ware",
    "tags": ["teapot", "gosu-blue", "handpainted", "tea-ceremony", "arita"],
    "price": "¥28,500",
}

PRODUCT_VASE = {
    "id": "gid://shopify/Product/11223",
    "title": "Noborigama Ash Glaze Flower Vase — 登り窯灰釉花瓶",
    "description": (
        "登り窯で焼かれた灰釉花瓶。自然の灰が窯の中で溶け、一つとして同じ模様のない"
        "偶然の美を生み出します。高さ25cm。一輪挿しに最適。"
    ),
    "category": "Vases & Décor",
    "tags": ["vase", "ash-glaze", "noborigama", "wabi-sabi", "one-of-a-kind"],
    "price": "¥45,000",
}


# =============================================================================
# PROD-Ready Mock LLM Responses — Per Template
# =============================================================================

# === REWRITER TEMPLATES ===

MOCK_PRODUCT_DESCRIPTION_RESPONSE = """{
  "title": "Celadon Jade Rice Bowl — Handcrafted Arita Porcelain",
  "description": "<p>Born from the same kiln that has shaped Arita porcelain since 1923, this rice bowl carries a century of mastery in every curve.</p><p>Our artisans hand-throw each bowl on the wheel — never molded — using locally sourced Amakusa clay prized for its silken texture and enduring strength. After bisque firing, natural Gosu cobalt is painted by hand, and the bowl is dipped in our proprietary celadon glaze before its final 36-hour firing at 1300°C. The result: our signature <em>jade whisper</em> finish that deepens with daily use.</p><ul><li><strong>Diameter:</strong> 12 cm | <strong>Height:</strong> 7 cm</li><li><strong>Material:</strong> Amakusa porcelain clay with celadon glaze</li><li><strong>Dishwasher safe</strong> — crafted for everyday reverence</li></ul><p>In the spirit of <em>Yō-no-bi</em> — the beauty of use — this bowl is designed to be held, filled, and cherished at every meal.</p>",
  "discovered_values": [
    {"name": "Heritage", "value": "Fourth-generation Arita workshop, est. 1923"},
    {"name": "Process", "value": "23-step, 6-week handcrafting process"},
    {"name": "Material", "value": "Amakusa clay with proprietary celadon glaze"}
  ]
}"""

MOCK_PRODUCT_TITLE_RESPONSE = """{
  "title": "Celadon Jade Rice Bowl — Handcrafted Arita Porcelain Since 1923",
  "alternatives": [
    "Artisan Celadon Rice Bowl — Jade Whisper Finish by Takumi Ceramics",
    "Hand-Thrown Arita Porcelain Rice Bowl — Heritage Celadon Glaze",
    "Takumi Jade Rice Bowl — Fourth-Generation Arita Craft"
  ]
}"""

MOCK_COLLECTION_RESPONSE = """{
  "description": "<p>Our tableware collection is a quiet invitation to slow down. Each piece — from rice bowls to serving plates — is hand-thrown in our Arita workshop using Amakusa clay, bisque-fired in our century-old noborigama kiln, and finished in our signature celadon jade glaze.</p><p>These are not decorative objects. They are daily companions designed in the spirit of <em>Yō-no-bi</em> — the Japanese philosophy of functional beauty. They will patina with your meals, your mornings, your years.</p><p>Four generations. Twenty-three steps. Six weeks per piece. Zero shortcuts.</p>",
  "meta_description": "Handcrafted Arita porcelain tableware by Takumi Ceramics. Fourth-generation artisan workshop est. 1923. Celadon jade finish. Made to be used daily."
}"""

MOCK_FAQ_RESPONSE = """{
  "faqs": [
    {
      "question": "Is this bowl dishwasher safe?",
      "answer": "Yes. We design every piece for daily use — that includes the dishwasher. Our celadon glaze is fired at 1300°C, making it highly durable. We do recommend avoiding abrasive detergents to preserve the jade whisper finish over time."
    },
    {
      "question": "Why does each bowl look slightly different?",
      "answer": "Because each bowl is hand-thrown on the wheel by a single artisan — we never use molds. Subtle variations in form, brushstroke, and glaze depth are a hallmark of authentic handcraft, not imperfections."
    },
    {
      "question": "What is the celadon 'jade whisper' finish?",
      "answer": "It's our proprietary celadon glaze, formulated by our founder in 1923 and unchanged since. When fired at 1300°C for 36 hours, it develops a soft, translucent jade-green surface that deepens subtly with use."
    },
    {
      "question": "Where is the clay sourced?",
      "answer": "We use Amakusa clay from Kumamoto Prefecture — one of Japan's finest porcelain clays. It's hand-wedged for 30 minutes before throwing to ensure a silken, air-free body."
    },
    {
      "question": "How long does it take to make one bowl?",
      "answer": "Each piece goes through 23 individual steps over approximately 6 weeks, from clay wedging to final kiln firing. We don't rush craft."
    },
    {
      "question": "Can I use this for microwave heating?",
      "answer": "Yes, our porcelain is microwave safe. The high-fire celadon glaze contains no metallic compounds. However, like all ceramics, avoid sudden temperature changes (e.g., freezer to microwave)."
    }
  ]
}"""

MOCK_LANDING_HERO_RESPONSE = """{
  "headline": "A Century of Craft in Your Hands",
  "subheadline": "Handcrafted Arita porcelain by Takumi Ceramics — fourth-generation artisans since 1923",
  "cta_text": "Explore the Collection",
  "hero_description": "Each piece is hand-thrown, kiln-fired for 36 hours, and finished in our signature jade whisper celadon glaze. Designed in the spirit of Yō-no-bi — the beauty of use — these are heirlooms meant to be used every day."
}"""


# === MARKETING TEMPLATES ===

MOCK_EMAIL_LAUNCH_RESPONSE = """{
  "subject": "Just Fired: The New Celadon Jade Collection",
  "preheader": "Four generations of craft, now in your kitchen.",
  "body": "<h2>A Quieter Kind of Luxury</h2><p>Dear friend of the workshop,</p><p>After six weeks in the kiln, our newest pieces are ready. The Celadon Jade Collection — rice bowls, side plates, and sake cups — carries our signature jade whisper finish that deepens with every meal you share.</p><p>Each piece is hand-thrown in our Arita studio by a single artisan, using the same celadon glaze recipe our founder created in 1923.</p><p>This is porcelain designed for your table, not your shelf.</p><p>Warm regards,<br/>The Takumi Family</p>",
  "cta_text": "See the Collection"
}"""

MOCK_EMAIL_ABANDONED_RESPONSE = """{
  "subject": "Your Jade Bowl Is Still Waiting",
  "preheader": "Hand-thrown, not mass-produced — it can wait, but not forever.",
  "body": "<p>We noticed you were admiring our Celadon Jade Rice Bowl.</p><p>We understand — a piece like this deserves a moment of thought. It took us six weeks and 23 steps to make it. Take the time you need.</p><p>Just know: because each bowl is individually hand-thrown, we only produce small batches. When this run sells out, the next batch won't emerge from the kiln for another six weeks.</p><p>If you have any questions about materials, care, or sizing, we're always here.</p>",
  "cta_text": "Return to Your Bowl"
}"""

MOCK_EMAIL_WELCOME_RESPONSE = """{
  "subject": "Welcome to the Workshop",
  "preheader": "Four generations of craft, one community.",
  "body": "<h2>Welcome, friend.</h2><p>Thank you for joining us. We are Takumi Ceramics — a fourth-generation family workshop in Arita, the birthplace of Japanese porcelain.</p><p>Since 1923, we have been making one kind of thing: functional pottery that belongs in your hands, not behind glass. We call this philosophy <em>Yō-no-bi</em> — the beauty of use.</p><p>As a member of our community, you'll be first to know when new pieces emerge from the kiln, and you'll hear the stories behind the craft.</p><p>Warm regards,<br/>The Takumi Family</p>",
  "cta_text": "Explore Our Craft"
}"""

MOCK_BLOG_POST_RESPONSE = """{
  "title": "The 23 Steps Behind Every Takumi Bowl",
  "meta_description": "Discover the six-week, 23-step process behind handcrafted Arita porcelain by Takumi Ceramics — from Amakusa clay to the jade whisper finish.",
  "content": "<h1>The 23 Steps Behind Every Takumi Bowl</h1><p>When you hold a Takumi bowl, you're holding six weeks of intentional craft. Here's what happens between the clay and your kitchen table.</p><h2>Week 1: The Clay</h2><p>It begins with Amakusa clay from Kumamoto Prefecture — a porcelain clay prized for its purity. Our artisans hand-wedge it for 30 minutes, working air pockets out of the body with a rhythmic, meditative motion unchanged for a century.</p><h2>Week 2: The Wheel</h2><p>A single artisan throws each piece on the wheel. No molds, no jigs. Just hands, clay, and a century of muscle memory passed from master to apprentice. Subtle asymmetries aren't flaws — they're signatures.</p><h2>Week 3-4: The First Fire</h2><p>Bisque firing at 900°C in our noborigama (climbing kiln) hardens the clay while keeping it porous enough to accept glaze. This kiln was built in the 1930s and still fires with Saga pinewood.</p><h2>Week 5: The Brush</h2><p>Using natural Gosu cobalt pigments, each piece is hand-painted. Blue lines flow across the surface in patterns that reference Arita's 400-year decorative tradition.</p><h2>Week 6: The Final Fire</h2><p>Dipped in our proprietary celadon glaze — formulated by our founder in 1923 — each piece enters the kiln for a final 36-hour firing at 1300°C. When it emerges, it carries our signature jade whisper finish: a soft, translucent green that deepens with daily use.</p><h2>The Philosophy</h2><p>We call this approach <em>Yō-no-bi</em> — the beauty of use. We don't make art for pedestals. We make tools for living.</p>",
  "tags": ["process", "arita-porcelain", "handcraft", "ceramics", "artisan"]
}"""

MOCK_AD_FACEBOOK_RESPONSE = """{
  "primary_text": "Hand-thrown in Arita since 1923. Our Celadon Jade Bowl carries a century of craft to your table.",
  "headline": "Porcelain With Provenance",
  "description": "Fourth-generation artisan pottery — made for daily use, not display cases.",
  "cta": "Shop Now"
}"""

MOCK_AD_GOOGLE_RESPONSE = """{
  "headlines": [
    "Handcrafted Arita Porcelain",
    "Celadon Jade Rice Bowls",
    "Since 1923 — Takumi Craft"
  ],
  "descriptions": [
    "Fourth-generation artisan pottery from Arita. 23-step, 6-week handcraft process. Shop now.",
    "Signature jade whisper celadon finish. Hand-thrown, never molded. Free shipping ¥10,000+"
  ],
  "path1": "Tableware",
  "path2": "Celadon-Collection"
}"""

MOCK_SOCIAL_HOOKS_RESPONSE = """{
  "hooks": [
    {
      "type": "Process",
      "caption": "23 steps. 6 weeks. 1 artisan. Zero molds. This is how a Takumi bowl comes to life — from Amakusa clay to jade whisper finish, every single piece is hand-thrown in our Arita workshop.",
      "hashtags": ["#AritaPorcelain", "#Handcrafted", "#TakumiCeramics", "#JapanesePottery", "#Celadon"],
      "overlay": "23 Steps to One Bowl",
      "copy_text": "23 steps. 6 weeks. 1 artisan. Zero molds. This is how a Takumi bowl comes to life — from Amakusa clay to jade whisper finish, every single piece is hand-thrown in our Arita workshop.\\n\\n#AritaPorcelain #Handcrafted #TakumiCeramics"
    },
    {
      "type": "Heritage",
      "caption": "1923 → 2026. Four generations of the Takumi family have kept this kiln burning in Arita. Same clay. Same glaze. Same reverence for the craft.",
      "hashtags": ["#FourGenerations", "#Heritage", "#MadeInJapan", "#AritaWare"],
      "overlay": "Since 1923",
      "copy_text": "1923 → 2026. Four generations of the Takumi family have kept this kiln burning in Arita. Same clay. Same glaze. Same reverence for the craft.\\n\\n#FourGenerations #Heritage #MadeInJapan"
    },
    {
      "type": "Aesthetic",
      "caption": "The jade whisper finish — our signature celadon glaze, unchanged since 1923. It deepens with every meal. Some call it patina. We call it a life well lived.",
      "hashtags": ["#CeladonGlaze", "#JadeWhisper", "#WabiSabi", "#SlowLiving"],
      "overlay": "Jade Whisper",
      "copy_text": "The jade whisper finish — our signature celadon glaze, unchanged since 1923.\\n\\n#CeladonGlaze #JadeWhisper #WabiSabi #SlowLiving"
    }
  ],
  "overlay_suggestions": [
    "23 Steps to One Bowl",
    "Since 1923",
    "Jade Whisper Finish",
    "Made to Be Used",
    "Yō-no-bi"
  ]
}"""


# =============================================================================
# Brand Voice Assertions — Words/phrases that MUST or MUST NOT appear
# =============================================================================

BRAND_VOICE_MUST_INCLUDE_KEYWORDS = [
    # At least ONE of these should appear in quality output
    "hand",  # handcrafted, hand-thrown, handmade
    "artisan",
    "Arita",
    "kiln",
    "celadon",
    "heritage",
    "craft",
]

BRAND_VOICE_BANNED_WORDS = [
    "cheap",
    "bargain",
    "deal",
    "discount",
    "mass-produced",
    "factory",
    "OMG",
    "game-changer",
    "hack",
    "incredible",
]
