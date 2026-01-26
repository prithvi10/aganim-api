# Technical Specification: Brand-Aware RAG Engine (Pass 0)

## 1. Objective
To retrieve and inject "Brand Context" into the AI rewriting process to ensure stylistic consistency and factual grounding in the merchant's unique history.

## 2. The Data Ingestion Pipeline (The "Brain" Setup)
We differentiate between "Established" and "Clean Slate" merchants.

### A. Scenario: Established Merchant (Auto-Scrape)
- **Sources:** `About Us`, `Our Story`, `Brand Philosophy`, and the latest 5 `Blog Posts`.
- **Method:** Use a headless crawler (e.g., Playwright/Puppeteer) to scrape public HTML.
- **Cleaning:** Pass raw HTML to a "Cleaning Agent" (GPT-4o-mini) to extract only brand-relevant text, stripping headers, footers, and scripts.

### B. Scenario: Clean Slate (Progressive Onboarding)
- **Flow:** A 3-step Polaris Wizard.
    1. **Brand Persona:** User selects 1 of 4 archetypes (Artisan Master, Modern Minimalist, Heritage House, Friendly Local).
    2. **Core Pillars:** User enters 3 bullet points about their process or materials.
    3. **Document Upload:** (Optional) User uploads a PDF/JPG brochure; OCR extracts text.

## 3. Storage Architecture (Multi-Tenant Vector DB)
- **Database:** Supabase (pgvector) or Pinecone.
- **Data Isolation:** Metadata filtering using `shop_id`. Shop A's vectors MUST NEVER be retrieved for Shop B.
- **Chunking Strategy:** Recursive character splitting (Chunk size: 500 characters, Overlap: 50 characters).
- **Embedding Model:** `text-embedding-3-small` (High performance/low cost).

## 4. The "Optimize" Retrieval Logic (Real-time)
When the 'Optimize' button is clicked:
1. **Query:** Embed the Japanese product title and description.
2. **Retrieve:** Perform a vector search to find the Top 3 most relevant "Brand Chunks" from the `store_context` table.
3. **Inject:** Pass these chunks into the LLM system prompt as `BRAND_HERITAGE_CONTEXT`.

## 5. Why RAG beats "Normal Prompting"
- **Memory:** Normal prompts have a small window; RAG can "remember" an entire 50-page brand history.
- **Precision:** RAG uses actual facts (e.g., "Kiln founded in 1640 in Gifu") rather than AI guessing the history.
- **Dynamic Adaptability:** If the merchant updates their "About Us" page, every new product description automatically reflects the new branding.