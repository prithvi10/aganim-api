import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import httpx, truststore
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date

from src.main.config.configs import (
    SYSTEM_PROMPT, 
    OPENAI_MODEL, 
    OPENAI_TEMPERATURE, 
    OPENAI_MAX_TOKENS
)
from src.main.logging.logger import get_logger
from src.main.db.db_transactions import record_successful_rewrite
from src.main.db.db_transactions import increment_monthly_rewrites_used  # backwards-compat for tests/patches
from src.main.service.fair_use import get_base_model_for_shop, get_effective_model, record_cost_from_usage

logger = get_logger(__name__)

load_dotenv()
## For NETSKOPE ##
## TODO : Remove before going to PROD
# <--- 2. Create an SSL Context that uses your System/Corporate Certs
ssl_context = truststore.SSLContext(httpx.create_ssl_context().protocol)

# <--- 3. Create a custom HTTP client using that SSL context
http_client = httpx.Client(verify=ssl_context)

class OpenAIService:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            http_client=http_client
        )
        self.system_prompt = SYSTEM_PROMPT

    def generate_copy(
        self,
        product_name: str,
        category: str,
        japanese_description: str,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> object:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not configured")

        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        The following Japanese text is pre-labeled with [Section] tags. Translate and beautify EACH section individually, preserving order and structure. Use the Architectural Rules from the system prompt.
        Pre-labeled Japanese Text:
        {japanese_description}
        """
        
        logger.info(f"Rewriting description using AI for product: {product_name}")
        logger.debug(f"User Content: {user_content}")

        prompt_to_use = system_prompt or self.system_prompt
        
        # Non-streaming call
        # Prefer structured JSON output to avoid parse failures (which would drop SEO + discovered_values).
        # If a model/environment doesn't support response_format, fall back gracefully.
        try:
            logger.debug("[OpenAI] response_format=json_object enabled")
            response = self.client.chat.completions.create(
                model=model or OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": prompt_to_use},
                    {"role": "user", "content": user_content}
                ],
                temperature=OPENAI_TEMPERATURE,
                max_tokens=OPENAI_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
        except TypeError:
            # Older SDKs may not accept response_format.
            logger.debug("[OpenAI] response_format unsupported; falling back")
            response = self.client.chat.completions.create(
                model=model or OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": prompt_to_use},
                    {"role": "user", "content": user_content}
                ],
                temperature=OPENAI_TEMPERATURE,
                max_tokens=OPENAI_MAX_TOKENS
            )
        
        return response # Return full object to access usage stats

    def generate_json(
        self,
        system_prompt: str,
        user_json: dict,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        """
        Generic helper for action-based agents: returns raw model text (expected to be JSON).
        Keeps existing copy-generation API intact while allowing new features to share the same client.
        """
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not configured")

        try:
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_json, ensure_ascii=False)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except TypeError:
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_json, ensure_ascii=False)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return response.choices[0].message.content or ""

    def generate_copy_stream(
        self,
        product_name: str,
        category: str,
        japanese_description: str,
        system_prompt: str | None = None,
        model: str | None = None,
    ):
        """
        Returns a generator (stream) from OpenAI.
        """
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        Original Japanese Text:
        {japanese_description}
        """
        
        logger.info(f"Stream-Rewriting description for product: {product_name}")
        
        prompt_to_use = system_prompt or self.system_prompt

        # Streaming call
        stream = self.client.chat.completions.create(
            model=model or OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt_to_use},
                {"role": "user", "content": user_content}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True} # Critical for accurate billing in streams
        )
        
        return stream

    async def stream_openai_response(
        self,
        product_name: str,
        category: str,
        japanese_description: str,
        db: Session,
        shop_domain: str,
        system_prompt: str | None = None
    ):
        """
        Generator function that:
        1. Streams chunks from OpenAI.
        2. Calculates total token usage (approximate for stream).
        3. Updates usage in DB after stream completes.
        4. Yields data to the client.
        """
        
        try:
            base_model = get_base_model_for_shop(db, shop_domain)
            model_override = get_effective_model(db, shop_domain, base_model)

            stream = self.generate_copy_stream(
                product_name=product_name,
                category=category,
                japanese_description=japanese_description,
                system_prompt=system_prompt,
                model=model_override,
            )

            full_content = ""
            total_usage = 0
            
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_content += content
                    yield content

                if hasattr(chunk, 'usage') and chunk.usage:
                    total_usage = chunk.usage.total_tokens

            if total_usage == 0 and full_content:
                 total_usage = len(full_content) // 4 + 100 

            # Internal-only cost accounting (best-effort)
            try:
                # Streaming does not always provide a clean breakdown; record with total tokens.
                record_cost_from_usage(db, shop_domain, {"total_tokens": int(total_usage or 0)}, model_used=model_override)
            except Exception as e:
                logger.warning(f"[FairUse] Cost accounting skipped for shop={shop_domain}: {e}")

            # Product-based gating: count 1 rewrite per successful request
            try:
                # Backwards-compatible name (and used by tests); internally maps to record_successful_rewrite.
                increment_monthly_rewrites_used(db, shop_domain, amount=1)
            except Exception as e:
                logger.warning(f"Unable to increment monthly rewrites for shop={shop_domain}: {e}")
                
        except Exception as e:
            logger.error(f"❌ Error during streaming: {e}")
            yield f"\n[Error generating response: {str(e)}]"

    def create_streaming_response(
        self,
        product_name: str,
        category: str,
        japanese_description: str,
        db: Session,
        shop_domain: str,
        system_prompt: str | None = None
    ):
        return StreamingResponse(
            self.stream_openai_response(
                product_name=product_name, 
                category=category, 
                japanese_description=japanese_description, 
                db=db, 
                shop_domain=shop_domain, 
                system_prompt=system_prompt
            ),
            media_type="text/event-stream" 
        )
