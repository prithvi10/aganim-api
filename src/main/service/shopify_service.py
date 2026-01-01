import httpx
import os
from src.main.logging.logger import get_logger

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

    async with httpx.AsyncClient() as client:
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
                logger.warning(f"⚠️ Could not find digests for title or body_html for product {product_id}")

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
            product { id title bodyHtml }
            userErrors { field message }
          }
        }
        """
        product_gid = f"gid://shopify/Product/{product_id}"
        variables = {
            "input": {
                "id": product_gid,
                "title": title,
                "bodyHtml": description
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json",
                headers=headers,
                json={"query": mutation, "variables": variables}
            )
            if resp.status_code != 200:
                logger.error(f"❌ GraphQL productUpdate failed {product_id} ({shop_domain}): {resp.status_code} {resp.text}")
                raise Exception(f"Failed to update product via GraphQL: {resp.status_code}")
            data = resp.json()
            user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
            if user_errors:
                logger.error(f"❌ productUpdate user errors: {user_errors}")
                raise Exception(f"GraphQL productUpdate error: {user_errors[0].get('message','Unknown error')}")
            updated = data.get("data", {}).get("productUpdate", {}).get("product", {})
            logger.info(
                f"✅ Product {product_id} updated via GraphQL (primary {shop_primary_locale}). "
                f"title_sample='{updated.get('title','')[:80]}'"
            )

            # Read back to verify what Shopify stored (debug visibility)
            verify_query = """
            query ($id: ID!) {
              product(id: $id) {
                title
                bodyHtml
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
                    vbody = vprod.get("bodyHtml", "") or ""
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
