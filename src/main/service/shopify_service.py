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
):
    """
    Creates or updates a translation for a given product ID using GraphQL.
    Fetches the latest content digest to ensure atomic updates.
    """
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    graphql_url = f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json"
    
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    product_gid = f"gid://shopify/Product/{product_id}"

    async with httpx.AsyncClient() as client:
        # 1. Fetch Digests
        # We need the digest of the PRIMARY content (title and body_html)
        digest_query = """
        query getTranslatableContent($resourceId: ID!) {
          translatableResource(resourceId: $resourceId) {
            translatableContent {
              key
              digest
              value
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

        except Exception as e:
            logger.error(f"Error fetching digests: {e}")
            raise

        # 2. Register Translation
        mutation = """
        mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
          translationsRegister(resourceId: $resourceId, translations: $translations) {
            userErrors {
              message
              field
            }
            translations {
              locale
              key
              value
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
            
            return True

        except Exception as e:
            logger.error(f"Error registering translation: {e}")
            raise

