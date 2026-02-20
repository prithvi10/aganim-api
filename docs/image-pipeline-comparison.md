# Image Generation Pipeline Comparison

A side-by-side analysis of the three image generation approaches used (or considered) in the platform: the **Rewriter Studio** refinement pipeline, the **Flux Fill** pixel-perfect pipeline, and the **Nano Banana** marketing pipeline.

---

## 1. Rewriter Studio — BiRefNet + Flux Redux

**Model chain:** `fal-ai/birefnet/v2` → `fal-ai/flux-pro/v1.1/redux`

### Pipeline Steps

| Step | What Happens | Tool |
|------|-------------|------|
| 1 | Download merchant image | httpx |
| 2 | Background removal (segmentation) | BiRefNet v2 |
| 3 | Encode isolated RGBA as base64 data URI | Python |
| 4 | Generate new studio background conditioned on product reference | Flux Pro Redux |
| 5 | Upload to R2 | R2 Storage |

### Prompt

```
Professional product photography background.
{brand_style}
Clean, well-lit studio environment that complements the product.
Subtle, non-distracting background with consistent global lighting.
High-end e-commerce aesthetic. Premium quality.
{extra_context}
```

When `brand_soul` is present, it injects up to 500 characters: `Brand aesthetic: <brand_soul>. The background should reflect this brand identity.`

### Fidelity Mechanism

BiRefNet gives pixel-perfect isolation, but Flux Redux is an **image-variation** model. It uses the product as a *style reference*, not a pixel source. The model regenerates the entire image — including the product — guided by the reference. It often alters labels, proportions, colors, or item counts.

**Fidelity rating: ~70–80%** — product is recognizable but not identical.

### Key Files

- `src/ecommerce/agents/image_refinement/agent.py` — agent orchestration
- `src/ecommerce/services/visual_service.py` — `isolate_product()` + `refine_product()`
- `src/ecommerce/agents/visual/prompts.py` — `build_inpaint_prompt()`

---

## 2. Flux Fill — Pixel-Perfect Inpainting

**Model chain:** `fal-ai/birefnet/v2` → PIL compositing → `fal-ai/flux-pro/v1/fill`

### Pipeline Steps

| Step | What Happens | Tool |
|------|-------------|------|
| 1 | Download merchant image | httpx |
| 2 | Background removal (segmentation) | BiRefNet v2 |
| 3 | **Split objects** — connected-components labelling on alpha channel to separate individual products | PIL + scipy `ndimage.label` |
| 4 | **Auto-layout** — deterministic placement templates (HeroCenter / DuoOffset / TrioArc / ShelfGrid) based on object count | Pure Python |
| 5 | **Composite + Mask** — paste objects onto 1024×1024 white canvas; generate binary mask (product=0/black, background=255/white) with erode + Gaussian blur feathering | PIL |
| 6 | **Inpaint** — send canvas + mask to Flux Fill; the model paints ONLY the white (255) regions | Flux Fill |
| 7 | Upload to R2 | R2 Storage |

### Prompt

```
Professional marketing product photography.
The product is placed on a {surface}.
{style_description}
{props_line}
{brand_style}
High-end e-commerce quality, 8k resolution.
The lighting is consistent, casting realistic soft shadows from the product onto the generated environment.
No text, words, letters, logos, or writing of any kind. Purely visual.
```

This prompt is purely visual — it describes surfaces (polished marble, dark slate, etc.), style descriptions from 10 presets, and auto-inferred props (coffee beans, citrus slices, etc.) based on product signals (name, type, tags).

### Fidelity Mechanism

**Mathematical guarantee.** A binary mask tells the model: "these pixels (0/black) are locked — do not touch them. Only paint on these pixels (255/white)." The actual product pixels from the merchant's image are pasted onto the canvas programmatically by PIL. The AI never sees or regenerates them. The feathered edge (erode + Gaussian blur) creates a smooth transition so shadows/reflections blend naturally.

**Fidelity rating: 100%** — product pixels are literally untouched.

### Complexity

This approach requires:
- **scipy** for connected-components labelling (`ndimage.label`)
- **numpy** for array manipulation
- **PIL/Pillow** for compositing, mask generation, eroding, feathering
- 4 layout templates for 1–6 objects
- Edge-case handling (noise filtering via `_MIN_OBJECT_AREA`, fallback for missing scipy)
- Feathering parameters (`_MASK_FEATHER_RADIUS`, `_MASK_ERODE_PX`) need tuning

### Key Files

- `src/ecommerce/services/visual_layout.py` — `split_objects()`, `auto_layout()`, `composite_and_mask()`
- `src/ecommerce/services/visual_service.py` — `FLUX_FILL_MODEL`
- `src/ecommerce/agents/visual/prompts.py` — `build_styled_background_prompt()`, `infer_props()`, `AD_STYLE_PROMPTS`, `_STYLE_SURFACES`

---

## 3. Nano Banana — Google Imagen Edit

**Model:** `fal-ai/nano-banana/edit`

### Pipeline Steps

| Step | What Happens | Tool |
|------|-------------|------|
| 1 | Send merchant image URL directly to Nano Banana | Nano Banana API |
| 2 | Download result | httpx |
| 3 | Upload to R2 | R2 Storage |

No isolation, no compositing, no masking.

### Prompt

```
Professional marketing product photo for Instagram.
Place the exact product from the reference image in a beautiful, well-lit setting with complementary styling and props.
Preserve the product faithfully -- same shape, colors, labels, and packaging.
{brand_style}
High-quality e-commerce photography. Eye-catching composition.
No text, words, letters, logos, or watermarks.
```

The prompt explicitly prioritises fidelity. `brand_style` is supported but **disabled by default** (`use_brand_style=False`) to avoid distracting the model from the reference image.

### Fidelity Mechanism

Entirely **prompt-driven**. The instruction "Preserve the product faithfully" asks the model to respect the reference, but there is no hard pixel constraint. Google Imagen is very good at this in practice, but it *can* make subtle changes.

**Fidelity rating: ~90–95%** — much better than Flux Redux, but not pixel-guaranteed.

### Key Files

- `src/ecommerce/services/product_ad_generator.py` — `ProductAdGenerator` class
- `src/ecommerce/agents/visual/prompts.py` — `build_nano_banana_prompt()`, `NANO_BANANA_MARKETING_TEMPLATE`

---

## Full Comparison Matrix

| Dimension | Rewriter (BiRefNet + Flux Redux) | Flux Fill (Pixel-Perfect) | Nano Banana (Imagen) |
|---|---|---|---|
| **API calls** | 2 | 2 (BiRefNet + Flux Fill) | 1 |
| **PIL/Python steps** | 0 | 3 (split, layout, composite+mask) | 0 |
| **Dependencies** | fal-client, httpx | fal-client, httpx, PIL, numpy, scipy | fal-client, httpx |
| **Lines of code** | ~60 (agent) | ~300+ (visual_layout.py) + agent | ~40 (ProductAdGenerator) |
| **Product fidelity** | **~70–80%** (variation model, can alter product) | **100%** (mask-protected pixels) | **~90–95%** (prompt-guided, very faithful) |
| **Background quality** | Good studio backgrounds, but conservative/plain | Good, style-aware with props inference, but can look "composited" (seam artifacts) | **Best** — natural scene with realistic lighting, shadows, reflections |
| **Style support** | No (just "studio background") | Yes — 10 styles, auto-inferred props, surface selection | No explicit style selector (prompt-driven) |
| **Brand Soul** | Always injected (500 chars) | Injected via `_distill_brand_aesthetic` (200 chars) | Supported but disabled by default |
| **Text handling** | Not addressed | Prompt says "no text" | Prompt says "no text" |
| **Cost per image** | ~$0.05 (BiRefNet free + Redux $0.05/MP) | ~$0.05 (BiRefNet free + Fill $0.05/MP) | **$0.039** |
| **Latency** | Medium (2 sequential API calls) | **Highest** (2 API calls + heavy PIL processing) | **Lowest** (1 API call) |
| **Failure modes** | Product alteration (wrong bottles, colors) | Object splitting errors (extra/missing items), visible seam at mask edge, hard dependency on scipy | Subtle product changes possible, no explicit style control |
| **Maintenance burden** | Low | **High** — connected-components, 4 layout templates, feathering params, edge cases | **Lowest** |

---

## Summary

- **If #1 priority is literal pixel-for-pixel product preservation**, Flux Fill is the only option that guarantees it. But it comes at the cost of significant code complexity (300+ lines of PIL/scipy), more failure modes (object splitting bugs, visible seams), and the highest latency.

- **If #1 priority is output quality** (realistic lighting, natural scenes, professional-looking Instagram posts), Nano Banana produces the best-looking results at the lowest cost and simplest code, with ~90–95% fidelity that is usually indistinguishable from the original.

- **The Rewriter pipeline** (BiRefNet + Flux Redux) sits in an awkward middle: it has the complexity of isolation without the fidelity guarantee of masking, and produces the least faithful product reproduction of the three because Flux Redux is a variation model.

### The Fundamental Tension

**Pixel fidelity vs. visual quality vs. complexity.** Flux Fill guarantees pixels but can look "composited." Nano Banana looks natural but can subtly alter the product. A hybrid approach (Flux Fill for the product + Nano Banana for the scene) would combine both strengths but adds even more pipeline complexity.

### Current Usage

| Feature | Pipeline Used |
|---------|--------------|
| Rewriter Studio — product image cleanup | BiRefNet + Flux Redux |
| Marketing Studio — social media ad creative | Nano Banana |
| Flux Fill pipeline | Code exists in `visual_layout.py` but not actively wired |
