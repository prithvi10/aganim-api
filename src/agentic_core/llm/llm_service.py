"""
LLMService - Unified Gateway/Adapter for OpenAI API calls.

Supports both legacy text generation and new structured outputs for agents.
Tracks token usage for cost accounting via optional callback.
"""

import os
from typing import Callable, TYPE_CHECKING, Type, TypeVar, Optional, Dict, Any
from pydantic import BaseModel
from openai import AsyncOpenAI, APIError
import httpx

from src.shared.logging.logger import get_logger
from src.shared.config.configs import OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_MAX_TOKENS
from .usage import LLMUsage, AccumulatedUsage

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Type alias for the usage callback
UsageCallback = Callable[[dict], None]

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


def _create_http_client() -> Optional[httpx.AsyncClient]:
    """
    Create an HTTP client with proper SSL context for corporate proxies.
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
        generate_text() - Legacy wrapper for unstructured text
        generate_structured() - Pydantic-enforced structured outputs
        generate_json() - JSON-formatted text response

    Usage Tracking:
        If a usage_callback is provided, it is called after each LLM call
        with a dict containing prompt_tokens, completion_tokens, reasoning_tokens,
        total_tokens, and model.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        db: Optional["Session"] = None,
        shop_domain: Optional[str] = None,
        usage_callback: Optional[UsageCallback] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        # Legacy: db/shop_domain kept for backward compat
        self.db = db
        self.shop_domain = shop_domain
        self._usage_callback = usage_callback

        # Usage tracking
        self.last_usage: Optional[LLMUsage] = None
        self.accumulated_usage: AccumulatedUsage = AccumulatedUsage()

        if self.api_key:
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

    def _track_usage(self, usage: Any, model: str) -> LLMUsage:
        """Extract and track token usage from OpenAI response."""
        llm_usage = LLMUsage(model=model)

        if usage:
            if isinstance(usage, dict):
                llm_usage.prompt_tokens = int(usage.get("prompt_tokens", 0))
                llm_usage.completion_tokens = int(usage.get("completion_tokens", 0))
                llm_usage.reasoning_tokens = int(usage.get("reasoning_tokens", 0))
                llm_usage.total_tokens = int(usage.get("total_tokens", 0))
            else:
                llm_usage.prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                llm_usage.completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                llm_usage.reasoning_tokens = int(getattr(usage, "reasoning_tokens", 0) or 0)
                llm_usage.total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

        self.last_usage = llm_usage
        self.accumulated_usage.add(llm_usage)

        # Fire usage callback if provided
        if self._usage_callback and llm_usage.total_tokens > 0:
            try:
                usage_dict = {
                    "prompt_tokens": llm_usage.prompt_tokens,
                    "completion_tokens": llm_usage.completion_tokens,
                    "reasoning_tokens": llm_usage.reasoning_tokens,
                    "total_tokens": llm_usage.total_tokens,
                    "model": model,
                }
                self._usage_callback(usage_dict)
                logger.debug(
                    "[LLM] Usage callback fired tokens=%d model=%s",
                    llm_usage.total_tokens,
                    model,
                )
            except Exception as e:
                logger.warning("[LLM] Usage callback failed: %s", e)

        return llm_usage

    def get_accumulated_usage(self) -> AccumulatedUsage:
        """Get accumulated usage for cost recording."""
        return self.accumulated_usage

    def reset_usage(self) -> None:
        """Reset accumulated usage (call after recording costs)."""
        self.accumulated_usage.reset()
        self.last_usage = None

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Legacy wrapper for unstructured text generation."""
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
            llm_usage = self._track_usage(response.usage, model)

            logger.info(
                "[LLM] Text Gen | Model: %s | In: %s | Out: %s | Total Accumulated: %s",
                model,
                llm_usage.prompt_tokens,
                llm_usage.completion_tokens,
                self.accumulated_usage.total_tokens,
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
        """Structured output wrapper using Pydantic enforcement."""
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

            llm_usage = self._track_usage(response.usage, model)

            logger.info(
                "[LLM] Structured | Model: %s | Type: %s | In: %s | Out: %s | Total Accumulated: %s",
                model,
                response_format.__name__,
                llm_usage.prompt_tokens,
                llm_usage.completion_tokens,
                self.accumulated_usage.total_tokens,
            )

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
        """Generate JSON-formatted text response (no Pydantic validation)."""
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
            llm_usage = self._track_usage(response.usage, model)

            logger.info(
                "[LLM] JSON Gen | Model: %s | In: %s | Out: %s | Total Accumulated: %s",
                model,
                llm_usage.prompt_tokens,
                llm_usage.completion_tokens,
                self.accumulated_usage.total_tokens,
            )

            return response.choices[0].message.content or "{}"

        except TypeError:
            logger.debug("[LLM] response_format unsupported; falling back")
            del kwargs["response_format"]
            response = await self.client.chat.completions.create(**kwargs)
            self._track_usage(response.usage, model)
            return response.choices[0].message.content or "{}"
        except Exception as e:
            logger.error("[LLM] JSON Generation Failed: %s", e)
            raise
