"""
LLMService - Unified Gateway/Adapter for OpenAI API calls.

Supports both legacy text generation and new structured outputs for agents.
Tracks token usage for fair_use cost accounting.
"""

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Type, TypeVar, Optional, Dict, Any
from pydantic import BaseModel
from openai import AsyncOpenAI, APIError
import httpx

from src.main.logging.logger import get_logger
from src.main.config.configs import OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_MAX_TOKENS

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMUsage:
    """Token usage from an LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
        }


@dataclass
class AccumulatedUsage:
    """Accumulated token usage across multiple LLM calls."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    models_used: list = field(default_factory=list)
    
    def add(self, usage: LLMUsage) -> None:
        """Add usage from a single LLM call."""
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.total_tokens += usage.total_tokens
        self.call_count += 1
        if usage.model and usage.model not in self.models_used:
            self.models_used.append(usage.model)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "models_used": self.models_used,
        }
    
    def reset(self) -> None:
        """Reset accumulated usage."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.total_tokens = 0
        self.call_count = 0
        self.models_used = []


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
    
    Usage Tracking:
        - last_usage: LLMUsage from the most recent call
        - accumulated_usage: AccumulatedUsage across all calls since last reset
        - get_accumulated_usage(): Get total usage for fair_use cost recording
        - reset_usage(): Clear accumulated usage (call after recording costs)
        
    Automatic Recording:
        If db and shop_domain are provided, usage is recorded to the database
        immediately after each LLM call - no manual recording needed.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        db: Optional["Session"] = None,
        shop_domain: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.db = db
        self.shop_domain = shop_domain
        
        # Usage tracking for fair_use integration
        self.last_usage: Optional[LLMUsage] = None
        self.accumulated_usage: AccumulatedUsage = AccumulatedUsage()
        
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
    
    def _track_usage(self, usage: Any, model: str) -> LLMUsage:
        """
        Extract and track token usage from OpenAI response.
        
        If db and shop_domain are configured, immediately records usage
        to the database for cost tracking.
        """
        llm_usage = LLMUsage(model=model)
        
        if usage:
            # Handle both dict-like and object-like usage objects
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
        
        # Store last usage and accumulate
        self.last_usage = llm_usage
        self.accumulated_usage.add(llm_usage)
        
        # Immediately record to database if session available
        if self.db and self.shop_domain and llm_usage.total_tokens > 0:
            try:
                from src.main.services.fair_use_service import record_cost_from_usage
                usage_dict = {
                    "prompt_tokens": llm_usage.prompt_tokens,
                    "completion_tokens": llm_usage.completion_tokens,
                    "reasoning_tokens": llm_usage.reasoning_tokens,
                    "total_tokens": llm_usage.total_tokens,
                }
                record_cost_from_usage(
                    db=self.db,
                    shop_domain=self.shop_domain,
                    usage=usage_dict,
                    model_used=model,
                )
                logger.debug(
                    "[LLM] Usage recorded shop=%s tokens=%d model=%s",
                    self.shop_domain,
                    llm_usage.total_tokens,
                    model,
                )
            except Exception as e:
                logger.warning("[LLM] Failed to record usage to database: %s", e)
        
        return llm_usage
    
    def get_accumulated_usage(self) -> AccumulatedUsage:
        """Get accumulated usage for fair_use cost recording."""
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
            
            # Track usage for fair_use integration
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
            
            # Track usage for fair_use integration
            llm_usage = self._track_usage(response.usage, model)
            
            logger.info(
                "[LLM] Structured | Model: %s | Type: %s | In: %s | Out: %s | Total Accumulated: %s",
                model,
                response_format.__name__,
                llm_usage.prompt_tokens,
                llm_usage.completion_tokens,
                self.accumulated_usage.total_tokens,
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
            
            # Track usage for fair_use integration
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
            # Older SDK may not support response_format; fall back
            logger.debug("[LLM] response_format unsupported; falling back")
            del kwargs["response_format"]
            response = await self.client.chat.completions.create(**kwargs)
            # Track usage for fallback too
            self._track_usage(response.usage, model)
            return response.choices[0].message.content or "{}"
        except Exception as e:
            logger.error("[LLM] JSON Generation Failed: %s", e)
            raise
