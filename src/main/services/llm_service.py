"""
LLMService - Unified Gateway/Adapter for OpenAI API calls.

Supports both legacy text generation and new structured outputs for agents.
"""

import os
from typing import Type, TypeVar, Optional
from pydantic import BaseModel
from openai import AsyncOpenAI, APIError
import httpx

from src.main.logging.logger import get_logger
from src.main.config.configs import OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_MAX_TOKENS

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def _create_http_client() -> Optional[httpx.AsyncClient]:
    """
    Create an HTTP client with proper SSL context for corporate proxies (e.g., Netskope).
    
    Uses truststore to leverage system/corporate certificates when available.
    Falls back to insecure client if truststore is unavailable.
    
    TODO: Remove insecure fallback before going to PROD
    """
    try:
        import truststore
        ssl_context = truststore.SSLContext(httpx.create_ssl_context().protocol)
        return httpx.AsyncClient(verify=ssl_context)
    except ImportError:
        logger.debug("[LLMService] truststore not installed; using default SSL")
        return None
    except Exception as exc:
        logger.warning("[LLMService] SSL context init failed; using insecure client: %s", exc)
        return httpx.AsyncClient(verify=False)


class LLMService:
    """
    Unified LLM service for all agent interactions with OpenAI.
    
    Methods:
        generate_text() - Legacy wrapper for unstructured text (creative copywriting)
        generate_structured() - NEW method for Pydantic-enforced structured outputs
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            # Create HTTP client with corporate SSL support (Netskope, etc.)
            http_client = _create_http_client()
            if http_client:
                self.client = AsyncOpenAI(api_key=self.api_key, http_client=http_client)
            else:
                self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None
            logger.warning("[LLMService] No API key provided - service will be unavailable")

    def _ensure_client(self) -> None:
        """Raise if client is not configured."""
        if not self.client:
            raise RuntimeError("LLMService: OPENAI_API_KEY not configured")

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Legacy wrapper for unstructured text generation.
        
        Used by:
            - Basic Tier copywriting
            - Creative content generation (Pass 1)
            - CopywriterAgent
        
        Args:
            prompt: The user prompt/content to process
            system_prompt: System instructions for the model
            model: OpenAI model to use (default: gpt-4o for quality)
            temperature: Creativity setting (0.0-2.0, default: 0.7)
            max_tokens: Max response length (optional)
        
        Returns:
            Generated text content as string
        """
        self._ensure_client()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await self.client.chat.completions.create(**kwargs)
            usage = response.usage
            
            if usage:
                logger.info(
                    "[LLM] Text Gen | Model: %s | In: %s | Out: %s",
                    model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                )
            
            content = response.choices[0].message.content
            return content or ""
            
        except APIError as e:
            logger.error("[LLM] API Error in generate_text: %s", e)
            raise
        except Exception as e:
            logger.error("[LLM] Unexpected error in generate_text: %s", e)
            raise

    async def generate_structured(
        self,
        prompt: str,
        response_format: Type[T],
        system_prompt: str = "You are a precise data processing agent.",
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> T:
        """
        NEW: Structured output wrapper for Agents.
        
        Uses OpenAI's beta.chat.completions.parse() for Pydantic enforcement.
        Returns actual Pydantic objects, not dicts/strings.
        
        Used by:
            - ComplianceAgent (ComplianceCheck schema)
            - PriceScoutAgent (PricingAnalysis schema)
            - Any agent needing deterministic JSON
        
        Args:
            prompt: The user prompt/content to process
            response_format: Pydantic model class to enforce
            system_prompt: System instructions for the model
            model: OpenAI model to use (default: gpt-4o-mini for cost)
            temperature: Creativity setting (default: 0.0 for determinism)
        
        Returns:
            Parsed Pydantic object of type T
        """
        self._ensure_client()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_format,
                temperature=temperature,
            )
            
            usage = response.usage
            if usage:
                logger.info(
                    "[LLM] Structured | Model: %s | Type: %s | In: %s | Out: %s",
                    model,
                    response_format.__name__,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                )
            
            # Returns the actual Pydantic object, not a dict/string
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError(f"Failed to parse response into {response_format.__name__}")
            return parsed
            
        except APIError as e:
            logger.error("[LLM] API Error in generate_structured: %s", e)
            raise
        except Exception as e:
            logger.error("[LLM] Structured Generation Failed: %s", e)
            raise

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant. Return valid JSON.",
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate JSON-formatted text response (unstructured, no Pydantic validation).
        
        For cases where you want JSON but don't have a strict schema.
        Prefer generate_structured() when you have a Pydantic model.
        
        Args:
            prompt: The user prompt
            system_prompt: System instructions
            model: OpenAI model to use
            temperature: Creativity setting
            max_tokens: Max response length
        
        Returns:
            Raw JSON string (caller must parse)
        """
        self._ensure_client()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await self.client.chat.completions.create(**kwargs)
            usage = response.usage
            
            if usage:
                logger.info(
                    "[LLM] JSON Gen | Model: %s | In: %s | Out: %s",
                    model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                )
            
            return response.choices[0].message.content or "{}"
            
        except TypeError:
            # Older SDK may not support response_format; fall back
            logger.debug("[LLM] response_format unsupported; falling back")
            del kwargs["response_format"]
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or "{}"
        except Exception as e:
            logger.error("[LLM] JSON Generation Failed: %s", e)
            raise
