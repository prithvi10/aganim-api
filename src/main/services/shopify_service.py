"""
ShopifyService - Shopify API interactions.

Moved from service/shopify_service.py to consolidate services.
"""

import httpx
import os
from src.main.logging.logger import get_logger
from src.main.utils.httpx_verify import ssl_verify_shopify

logger = get_logger(__name__)

async def create_shopify_translation(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
    title: str,
    description: str,
    target_locale: str
) -> None:
    """
    ACTION 2: DUAL-STEP TRANSLATION (READ BEFORE WRITE)
    Creates or updates a translation for a given product ID using GraphQL.
    1. Query translatableResource: Fetch the digest for the 'title' and 'body_html' of the product.
    2. Execute translationsRegister: Pass the new AI content, target_locale, and digests.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    graphql_url = f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json"
    
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    product_gid = f"gid://shopify/Product/{product_id}"

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        # STEP 1: READ (Fetch Digests)
        digest_query = """
        query getTranslatableContent($resourceId: ID!) {
          translatableResource(resourceId: $resourceId) {
            translatableContent {
              key
              digest
            }
          }
        }
        """
        
        try:
            response = await client.post(
                graphql_url, 
                headers=headers, 
                json={"query": digest_query, "variables": {"resourceId": product_gid}}
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Failed to fetch digests. Status: {response.status_code}, Body: {response.text}")
                raise Exception(f"Failed to fetch content digests: {response.status_code}")
            
            data = response.json()
            if "errors" in data:
                logger.error(f"❌ GraphQL Errors fetching digest: {data['errors']}")
                raise Exception("Failed to fetch content digests due to GraphQL error.")

            contents = data.get("data", {}).get("translatableResource", {}).get("translatableContent", [])
            
            title_digest = ""
            desc_digest = ""
            
            for item in contents:
                if item["key"] == "title":
                    title_digest = item["digest"]
                elif item["key"] == "body_html":
                    desc_digest = item["digest"]

            if not title_digest or not desc_digest:
                logger.error(f"❌ Missing digests for title/body_html for product {product_id}; aborting translationsRegister.")
                raise Exception("Missing content digests; cannot register translation.")

        except Exception as e:
            logger.error(f"Error fetching digests: {e}")
            raise

        # STEP 2: WRITE (Register Translation)
        mutation = """
        mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
          translationsRegister(resourceId: $resourceId, translations: $translations) {
            userErrors {
              message
              field
            }
          }
        }
        """
        
        variables = {
            "resourceId": product_gid,
            "translations": [
                {
                    "locale": target_locale,
                    "key": "title",
                    "value": title,
                    "translatableContentDigest": title_digest
                },
                {
                    "locale": target_locale,
                    "key": "body_html",
                    "value": description,
                    "translatableContentDigest": desc_digest
                }
            ]
        }

        try:
            response = await client.post(
                graphql_url, 
                headers=headers, 
                json={"query": mutation, "variables": variables}
            )
            
            if response.status_code != 200:
                logger.error(f"❌ GraphQL Mutation Failed. Status: {response.status_code}, Body: {response.text}")
                raise Exception("Failed to register translation.")
            
            result_data = response.json()
            user_errors = result_data.get("data", {}).get("translationsRegister", {}).get("userErrors", [])
            
            if user_errors:
                error_msg = user_errors[0]['message']
                logger.error(f"❌ Translation API Errors: {user_errors}")
                raise Exception(f"Shopify Translation Error: {error_msg}")
            
            logger.info(f"✅ Successfully registered translation for {target_locale} (Product {product_id}).")
            return None

        except Exception as e:
            logger.error(f"Error registering translation: {e}")
            raise


async def save_product_content_with_locale(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
    title: str,
    description: str,
    target_locale: str,
    shop_primary_locale: str,
) -> None:
    """
    ACTION 1: LOCALE ROUTING LOGIC
    ACTION 3: PREVENT "MASTER" OVERWRITE
    Save product content. If target locale is primary, update via REST.
    Otherwise, register translation via GraphQL.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    # IF PRIMARY: Update using GraphQL productUpdate (REST is deprecated)
    if target_locale == shop_primary_locale:
        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title descriptionHtml }
            userErrors { field message }
          }
        }
        """
        product_gid = f"gid://shopify/Product/{product_id}"
        variables = {
            "input": {
                "id": product_gid,
                "title": title,
                "descriptionHtml": description
            }
        }
        async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
            resp = await client.post(
                f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
                headers=headers,
                json={"query": mutation, "variables": variables}
            )
            if resp.status_code != 200:
                logger.error(f"❌ GraphQL productUpdate failed {product_id} ({shop_domain}): {resp.status_code} {resp.text}")
                raise Exception(f"Failed to update product via GraphQL: {resp.status_code}")
            data = resp.json()
            if "errors" in data:
                logger.error(f"❌ GraphQL Syntax Error: {data['errors']}")
                raise Exception(f"GraphQL Syntax Error: {data['errors'][0].get('message')}")
            user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
            if user_errors:
                logger.error(f"❌ productUpdate user errors: {user_errors}")
                raise Exception(f"GraphQL productUpdate error: {user_errors[0].get('message','Unknown error')}")
            updated = data.get("data", {}).get("productUpdate", {}).get("product", {})
            logger.info(
                f"✅ Product {product_id} updated via GraphQL (primary {shop_primary_locale}). "
                f"title_sample='{updated.get('title','')[:80]}'"
            )

            # Optional readback; enabled only when explicitly configured to avoid extra calls in tests.
            if os.getenv("ENABLE_SHOPIFY_VERIFY", "false").lower() == "true":
                verify_query = """
                query ($id: ID!) {
                  product(id: $id) {
                    title
                    descriptionHtml
                  }
                }
                """
                try:
                    verify_resp = await client.post(
                        f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
                        headers=headers,
                        json={"query": verify_query, "variables": {"id": product_gid}}
                    )
                    if verify_resp.status_code == 200:
                        verify_json = verify_resp.json()
                        vprod = verify_json.get("data", {}).get("product", {}) or {}
                        vtitle = vprod.get("title", "") or ""
                        vbody = vprod.get("descriptionHtml", "") or ""
                        logger.info(
                            f"[Verify] productUpdate readback pid={product_id} "
                            f"title_sample='{vtitle[:80]}' body_sample='{vbody[:80]}'"
                        )
                        if not vtitle or not vbody:
                            logger.warning(
                                f"[Verify] productUpdate returned empty title/body for pid={product_id}. "
                                f"raw_response={verify_json}"
                            )
                    else:
                        logger.warning(
                            f"[Verify] productUpdate readback failed {product_id}: "
                            f"status={verify_resp.status_code} body={verify_resp.text}"
                        )
                except Exception as e:
                    logger.warning(f"[Verify] productUpdate readback error {product_id}: {e}")
    
    # IF SECONDARY: Use GraphQL Translation mutation (Prevents "Master" overwrite)
    else:
        await create_shopify_translation(
            shop_domain=shop_domain,
            access_token=access_token,
            product_id=product_id,
            title=title,
            description=description,
            target_locale=target_locale
        )


async def save_product_metafields(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
    metafields: list[dict],
) -> None:
    """
    Save custom metafields to a Shopify product.
    
    Used to store agent-generated data like social hooks, pricing analysis, SEO data.
    
    Args:
        shop_domain: The shop domain (e.g., "myshop.myshopify.com")
        access_token: Shopify access token
        product_id: Product ID (numeric or GID)
        metafields: List of dicts with:
            - namespace: str (e.g., "crossborder_agent")
            - key: str (e.g., "social_hooks", "pricing_analysis")
            - value: str (JSON string)
            - type: str (e.g., "json")
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    
    # Ensure product_id is in GID format
    if str(product_id).startswith("gid://"):
        product_gid = str(product_id)
    else:
        product_gid = f"gid://shopify/Product/{product_id}"
    
    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { 
          id 
          metafields(first: 10) {
            edges {
              node {
                namespace
                key
              }
            }
          }
        }
        userErrors { field message }
      }
    }
    """
    
    # Format metafields for GraphQL
    metafield_inputs = [
        {
            "namespace": mf["namespace"],
            "key": mf["key"],
            "value": mf["value"],
            "type": mf.get("type", "json"),
        }
        for mf in metafields
    ]
    
    variables = {
        "input": {
            "id": product_gid,
            "metafields": metafield_inputs
        }
    }
    
    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": mutation, "variables": variables}
        )
        
        if resp.status_code != 200:
            logger.error(
                f"❌ Metafield save failed for product {product_id} ({shop_domain}): "
                f"{resp.status_code} {resp.text}"
            )
            raise Exception(f"Failed to save metafields: {resp.status_code}")
        
        data = resp.json()
        
        if "errors" in data:
            logger.error(f"❌ GraphQL Syntax Error in metafield save: {data['errors']}")
            raise Exception(f"GraphQL Syntax Error: {data['errors'][0].get('message')}")
        
        user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if user_errors:
            logger.error(f"❌ Metafield save user errors: {user_errors}")
            raise Exception(f"Metafield error: {user_errors[0].get('message', 'Unknown error')}")
        
        saved_metafields = data.get("data", {}).get("productUpdate", {}).get("product", {}).get("metafields", {})
        logger.info(
            f"✅ Metafields saved for product {product_id} ({shop_domain}). "
            f"Count: {len(metafield_inputs)}"
        )


# ---------------------------------------------------------------------------
# Product body read / template-section injection helpers
# ---------------------------------------------------------------------------

async def get_product_body(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
) -> str | None:
    """
    Fetch the current ``descriptionHtml`` for a product via GraphQL.

    Returns the HTML string, or ``None`` if the product can't be read.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    product_gid = (
        str(product_id)
        if str(product_id).startswith("gid://")
        else f"gid://shopify/Product/{product_id}"
    )
    query = """
    query getProductBody($id: ID!) {
      product(id: $id) { descriptionHtml }
    }
    """
    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": query, "variables": {"id": product_gid}},
        )
        if resp.status_code != 200:
            logger.warning(
                "get_product_body failed: %s %s (%s)",
                resp.status_code, resp.text, shop_domain,
            )
            return None
        data = resp.json()
        product = data.get("data", {}).get("product")
        if not product:
            return None
        return product.get("descriptionHtml") or ""


import re as _re
import json as _json


def faq_json_to_html(faq_json: str) -> str:
    """
    Convert FAQ JSON → collapsible ``<details>`` HTML wrapped with markers.

    Expected input format::

        {"faqs": [{"question": "…", "answer": "…"}, …]}

    Returns empty string if the input can't be parsed or has no FAQs.
    """
    try:
        data = _json.loads(faq_json) if isinstance(faq_json, str) else faq_json
        faqs = data.get("faqs", []) if isinstance(data, dict) else data
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not faqs:
        return ""
    parts = [
        "<!-- cba-faq-start -->",
        '<div class="cba-faq">',
        "<h3>Frequently Asked Questions</h3>",
    ]
    for faq in faqs:
        q = faq.get("question", "")
        a = faq.get("answer", "")
        if q:
            parts.append(f"<details><summary>{q}</summary><p>{a}</p></details>")
    parts.append("</div>")
    parts.append("<!-- cba-faq-end -->")
    return "\n".join(parts)


def hero_json_to_html(hero_json: str) -> str:
    """
    Convert Hero JSON → semantic HTML wrapped with markers.

    Expected input format::

        {"headline": "…", "subheadline": "…",
         "hero_description": "…", "cta_text": "…"}
    """
    try:
        data = _json.loads(hero_json) if isinstance(hero_json, str) else hero_json
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    headline = data.get("headline", "")
    sub = data.get("subheadline", "")
    desc = data.get("hero_description", "")
    cta = data.get("cta_text", "")
    if not any([headline, sub, desc]):
        return ""
    parts = [
        "<!-- cba-hero-start -->",
        '<div class="cba-hero">',
    ]
    if headline:
        parts.append(f"<h1>{headline}</h1>")
    if sub:
        parts.append(f"<p><strong>{sub}</strong></p>")
    if desc:
        parts.append(f"<p>{desc}</p>")
    if cta:
        parts.append(f"<p><em>{cta}</em></p>")
    parts.append("</div>")
    parts.append("<!-- cba-hero-end -->")
    return "\n".join(parts)


def inject_section(
    body_html: str,
    section_html: str,
    marker_start: str,
    marker_end: str,
    position: str = "append",
) -> str:
    """
    Replace an existing marker-delimited block, or inject at *position*.

    Args:
        body_html: Current product description HTML.
        section_html: The new section (including its own markers).
        marker_start: Opening marker comment, e.g. ``<!-- cba-faq-start -->``.
        marker_end: Closing marker comment.
        position: ``"append"`` (bottom) or ``"prepend"`` (top) when no
                  existing markers are found.

    Returns:
        Updated HTML.
    """
    pattern = _re.compile(
        _re.escape(marker_start) + r".*?" + _re.escape(marker_end),
        _re.DOTALL,
    )
    if pattern.search(body_html):
        return pattern.sub(section_html, body_html)
    body_html = body_html.strip() if body_html else ""
    if position == "prepend":
        return section_html + "\n" + body_html if body_html else section_html
    return body_html + "\n" + section_html if body_html else section_html


# ---------------------------------------------------------------------------
# Autonomous publishing helpers (Pro tier)
# ---------------------------------------------------------------------------

async def update_product_body(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
    html: str,
) -> None:
    """
    Update only the product descriptionHtml via GraphQL ``productUpdate``.
    
    Used by RewriterAgent autonomous publish for ``product/description`` template.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    product_gid = (
        str(product_id) if str(product_id).startswith("gid://")
        else f"gid://shopify/Product/{product_id}"
    )

    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id descriptionHtml }
        userErrors { field message }
      }
    }
    """
    variables = {"input": {"id": product_gid, "descriptionHtml": html}}

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": mutation, "variables": variables},
        )
        if resp.status_code != 200:
            raise Exception(f"update_product_body failed: {resp.status_code}")
        data = resp.json()
        user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if user_errors:
            raise Exception(f"update_product_body user error: {user_errors[0].get('message')}")
        logger.info("✅ Product body updated for %s (%s)", product_id, shop_domain)


async def update_variant_price(
    shop_domain: str,
    access_token: str,
    variant_id: int | str,
    price: str,
) -> None:
    """
    Update a product variant's price via GraphQL ``productVariantUpdate``.
    
    Used by PriceScoutAgent autonomous publish after guardrails validation.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    variant_gid = (
        str(variant_id) if str(variant_id).startswith("gid://")
        else f"gid://shopify/ProductVariant/{variant_id}"
    )

    mutation = """
    mutation productVariantUpdate($input: ProductVariantInput!) {
      productVariantUpdate(input: $input) {
        productVariant { id price }
        userErrors { field message }
      }
    }
    """
    variables = {"input": {"id": variant_gid, "price": str(price)}}

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": mutation, "variables": variables},
        )
        if resp.status_code != 200:
            raise Exception(f"update_variant_price failed: {resp.status_code}")
        data = resp.json()
        user_errors = (
            data.get("data", {}).get("productVariantUpdate", {}).get("userErrors", [])
        )
        if user_errors:
            raise Exception(f"update_variant_price user error: {user_errors[0].get('message')}")
        logger.info("✅ Variant price updated for %s → %s (%s)", variant_id, price, shop_domain)


async def get_default_blog_id(
    shop_domain: str,
    access_token: str,
) -> str | None:
    """
    Fetch the first (default) blog ID for a shop via REST API.

    Shopify stores always have at least one blog (usually called "News").
    Returns the blog ID as a string, or ``None`` if no blogs exist.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    url = f"https://{shop_domain}/admin/api/{shopify_api_version}/blogs.json?limit=1"

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(
                "get_default_blog_id failed: %s %s (%s)",
                resp.status_code, resp.text, shop_domain,
            )
            return None
        blogs = resp.json().get("blogs", [])
        if not blogs:
            logger.warning("No blogs found for shop=%s", shop_domain)
            return None
        blog_id = str(blogs[0]["id"])
        logger.info("Default blog_id=%s for shop=%s", blog_id, shop_domain)
        return blog_id


async def create_article(
    shop_domain: str,
    access_token: str,
    blog_id: int | str,
    title: str,
    body_html: str,
) -> dict:
    """
    Create a blog article via REST API.
    
    Used by MarketingAgent autonomous publish for ``product/blog-post`` template.
    
    Returns:
        Dict with the created article data.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    url = f"https://{shop_domain}/admin/api/{shopify_api_version}/blogs/{blog_id}/articles.json"
    payload = {
        "article": {
            "title": title,
            "body_html": body_html,
            "published": True,
        }
    }

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            raise Exception(f"create_article failed: {resp.status_code} {resp.text}")
        article = resp.json().get("article", {})
        logger.info("✅ Article created id=%s blog=%s (%s)", article.get("id"), blog_id, shop_domain)
        return article


async def trigger_flow_event(
    shop_domain: str,
    access_token: str,
    event_topic: str,
    payload: dict,
) -> None:
    """
    Trigger a Shopify Flow event via GraphQL ``flowTriggerReceive``.
    
    Used by MarketingAgent autonomous publish for ``marketing/email-*`` templates.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    mutation = """
    mutation flowTriggerReceive($body: String!) {
      flowTriggerReceive(body: $body) {
        userErrors { field message }
      }
    }
    """
    import json as _json
    body_str = _json.dumps({"topic": event_topic, **payload})
    variables = {"body": body_str}

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": mutation, "variables": variables},
        )
        if resp.status_code != 200:
            raise Exception(f"trigger_flow_event failed: {resp.status_code}")
        data = resp.json()
        user_errors = (
            data.get("data", {}).get("flowTriggerReceive", {}).get("userErrors", [])
        )
        if user_errors:
            raise Exception(f"trigger_flow_event error: {user_errors[0].get('message')}")
        logger.info("✅ Flow event triggered topic=%s (%s)", event_topic, shop_domain)


async def update_product_seo(
    shop_domain: str,
    access_token: str,
    product_id: int | str,
    seo_title: str,
    seo_description: str,
) -> None:
    """
    Update a product's SEO title and description via GraphQL ``productUpdate``.
    
    Used by the ``seo_optimize`` publish action.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    product_gid = (
        str(product_id) if str(product_id).startswith("gid://")
        else f"gid://shopify/Product/{product_id}"
    )

    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": {
            "id": product_gid,
            "seo": {
                "title": seo_title,
                "description": seo_description,
            },
        }
    }

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
            headers=headers,
            json={"query": mutation, "variables": variables},
        )
        if resp.status_code != 200:
            raise Exception(f"update_product_seo failed: {resp.status_code}")
        data = resp.json()
        user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if user_errors:
            raise Exception(f"update_product_seo user error: {user_errors[0].get('message')}")
        logger.info("✅ Product SEO updated for %s (%s)", product_id, shop_domain)


async def create_collection(
    shop_domain: str,
    access_token: str,
    title: str,
    description_html: str,
    product_ids: list[str] | None = None,
) -> dict:
    """
    Create a Custom Collection via GraphQL and optionally add products.

    Args:
        shop_domain: Shop domain
        access_token: Shopify access token
        title: Collection title
        description_html: Collection description HTML
        product_ids: Optional list of product GIDs to add

    Returns:
        Dict with the created collection data.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    graphql_url = f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json"

    create_mutation = """
    mutation collectionCreate($input: CollectionInput!) {
      collectionCreate(input: $input) {
        collection { id title descriptionHtml }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": {
            "title": title,
            "descriptionHtml": description_html,
        }
    }

    async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
        resp = await client.post(
            graphql_url,
            headers=headers,
            json={"query": create_mutation, "variables": variables},
        )
        if resp.status_code != 200:
            raise Exception(f"collectionCreate failed: {resp.status_code} {resp.text}")

        data = resp.json()
        user_errors = (
            data.get("data", {}).get("collectionCreate", {}).get("userErrors", [])
        )
        if user_errors:
            raise Exception(f"collectionCreate error: {user_errors[0].get('message')}")

        collection = (
            data.get("data", {}).get("collectionCreate", {}).get("collection", {})
        )
        collection_id = collection.get("id")
        logger.info(
            "✅ Collection created id=%s title=%s (%s)",
            collection_id, title, shop_domain,
        )

        # Add products if provided
        if product_ids and collection_id:
            gids = [
                pid if pid.startswith("gid://") else f"gid://shopify/Product/{pid}"
                for pid in product_ids
            ]
            add_mutation = """
            mutation collectionAddProducts($id: ID!, $productIds: [ID!]!) {
              collectionAddProducts(id: $id, productIds: $productIds) {
                collection { id }
                userErrors { field message }
              }
            }
            """
            add_resp = await client.post(
                graphql_url,
                headers=headers,
                json={
                    "query": add_mutation,
                    "variables": {"id": collection_id, "productIds": gids},
                },
            )
            if add_resp.status_code == 200:
                add_data = add_resp.json()
                add_errors = (
                    add_data.get("data", {})
                    .get("collectionAddProducts", {})
                    .get("userErrors", [])
                )
                if add_errors:
                    logger.warning(
                        "collectionAddProducts partial error: %s (%s)",
                        add_errors[0].get("message"),
                        shop_domain,
                    )
                else:
                    logger.info(
                        "✅ Added %d products to collection %s (%s)",
                        len(gids), collection_id, shop_domain,
                    )
            else:
                logger.warning(
                    "collectionAddProducts HTTP error: %s (%s)",
                    add_resp.status_code, shop_domain,
                )

        return collection


def get_shop_credentials(db, shop_domain: str) -> dict:
    """
    Retrieve shop credentials needed for autonomous publishing.
    
    Returns a dict with access_token, meta_access_token, meta_page_id,
    and price_guardrails from the Shop model.
    """
    from src.main.db.db_models import Shop

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return {}
    return {
        "access_token": shop.access_token,
        "meta_access_token": getattr(shop, "meta_access_token", None),
        "meta_page_id": getattr(shop, "meta_page_id", None),
        "price_guardrails": getattr(shop, "price_guardrails", None),
    }
