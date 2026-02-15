"""
SerpService - Search Engine Results Page service for competitor analysis.

Provides structured SERP data for agents like PriceScoutAgent.
"""
from __future__ import annotations

import os
from typing import Optional, List, Dict
from dataclasses import dataclass
import httpx

from src.shared.logging.logger import get_logger
from src.shared.config.configs import SERP_API_KEY, SERP_API_URL
from src.shared.utils.httpx_verify import ssl_verify_serp

logger = get_logger(__name__)


@dataclass
class SerpResult:
    """Structured SERP result."""
    title: str
    snippet: str
    link: str
    position: int


@dataclass
class ShoppingResult:
    """Structured Google Shopping result with price data."""
    title: str
    price: str                    # Display string (e.g., "$45.00")
    extracted_price: float        # Numeric value for calculations
    source: str                   # Merchant name (e.g., "Amazon", "Etsy")
    link: str
    thumbnail: Optional[str] = None
    shipping: Optional[str] = None
    position: int = 0


class SerpService:
    """
    Service for fetching Search Engine Results Page data.

    Used by:
        - PriceScoutAgent for competitor pricing
        - Future CompetitorAnalysisAgent

    Methods:
        search() - Generic SERP search
        get_competitor_prices() - Convenience method for pricing use case
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        self.api_key = api_key or SERP_API_KEY or os.getenv("SERP_API_KEY")
        self.api_url = api_url or SERP_API_URL or "https://serpapi.com/search"
        self.timeout = httpx.Timeout(5.0)

    async def search(
        self,
        query: str,
        num_results: int = 3,
        engine: str = "google",
        location: Optional[str] = None,
    ) -> List[SerpResult]:
        """
        Fetch top organic SERP results for a query.

        Args:
            query: Search query string
            num_results: Number of results to return (default: 3)
            engine: Search engine to use (default: google)
            location: Optional location for localized results

        Returns:
            List of SerpResult objects, empty list on failure
        """
        q = (query or "").strip()
        if not q:
            return []

        if not self.api_key:
            logger.warning("[SERP] API key not configured; skipping search")
            return []

        params = {
            "engine": engine,
            "q": q,
            "num": num_results,
            "api_key": self.api_key,
        }
        if location:
            params["location"] = location

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    verify=ssl_verify_serp(),
                ) as client:
                    resp = await client.get(self.api_url, params=params)

                    if resp.status_code != 200:
                        logger.warning(
                            "[SERP] non_200 status=%s attempt=%s q=%s body=%s",
                            resp.status_code,
                            attempt + 1,
                            q[:30],
                            resp.text[:200],
                        )
                        continue

                    data = resp.json() or {}
                    organic = data.get("organic_results") or []

                    results: List[SerpResult] = []
                    for i, item in enumerate(organic[:num_results]):
                        title = str(item.get("title") or "").strip()
                        snippet = str(item.get("snippet") or "").strip()
                        link = str(
                            item.get("link") or item.get("url") or ""
                        ).strip()

                        if not (title or snippet or link):
                            continue

                        results.append(
                            SerpResult(
                                title=title,
                                snippet=snippet,
                                link=link,
                                position=i + 1,
                            )
                        )

                    if results:
                        logger.info(
                            "[SERP] query=%s results=%s",
                            q[:30],
                            len(results),
                        )
                        return results

            except Exception as e:
                logger.warning(
                    "[SERP] fetch_failed attempt=%s q=%s err=%s",
                    attempt + 1,
                    q[:30],
                    e,
                )

        logger.warning("[SERP] giving up after retries q=%s", q[:30])
        return []

    async def search_shopping(
        self,
        query: str,
        num_results: int = 20,
        location: Optional[str] = "United States",
    ) -> List[ShoppingResult]:
        """
        Fetch Google Shopping results for a product query.
        """
        q = (query or "").strip()
        if not q:
            return []

        if not self.api_key:
            logger.warning("[SERP] API key not configured; skipping shopping_light search")
            return []

        params = {
            "engine": "google_shopping_light",
            "q": q,
            "num": num_results,
            "api_key": self.api_key,
        }
        if location:
            params["location"] = location

        shopping_timeout = httpx.Timeout(8.0)

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=shopping_timeout,
                    verify=ssl_verify_serp(),
                ) as client:
                    resp = await client.get(self.api_url, params=params)

                    if resp.status_code != 200:
                        logger.warning(
                            "[SERP] shopping_light non_200 status=%s attempt=%s q=%s body=%s",
                            resp.status_code,
                            attempt + 1,
                            q[:30],
                            resp.text[:200],
                        )
                        continue

                    data = resp.json() or {}
                    shopping_results = data.get("shopping_results") or []

                    results: List[ShoppingResult] = []
                    for i, item in enumerate(shopping_results[:num_results]):
                        title = str(item.get("title") or "").strip()

                        extracted_price = item.get("extracted_price")
                        if extracted_price is None:
                            price_str = str(item.get("price") or "")
                            try:
                                cleaned = price_str.replace("$", "").replace(",", "").strip()
                                extracted_price = float(cleaned) if cleaned else None
                            except (ValueError, TypeError):
                                extracted_price = None

                        if extracted_price is None or extracted_price <= 0:
                            continue

                        price = str(item.get("price") or f"${extracted_price:.2f}")
                        source = str(item.get("source") or item.get("merchant") or "Unknown").strip()
                        link = str(item.get("link") or item.get("product_link") or "").strip()
                        thumbnail = item.get("thumbnail")
                        shipping = item.get("shipping") or item.get("delivery")

                        if not title:
                            continue

                        results.append(
                            ShoppingResult(
                                title=title,
                                price=price,
                                extracted_price=float(extracted_price),
                                source=source,
                                link=link,
                                thumbnail=thumbnail,
                                shipping=str(shipping) if shipping else None,
                                position=i + 1,
                            )
                        )

                    if results:
                        logger.info(
                            "[SERP] shopping_light query=%s results=%s (filtered from %s)",
                            q[:30],
                            len(results),
                            len(shopping_results),
                        )
                        return results

            except Exception as e:
                logger.warning(
                    "[SERP] shopping_light fetch_failed attempt=%s q=%s err=%s",
                    attempt + 1,
                    q[:30],
                    e,
                )

        logger.warning("[SERP] shopping_light giving up after retries q=%s", q[:30])
        return []

    async def get_competitor_prices(
        self,
        product_name: str,
        category: str,
        num_results: int = 20,
    ) -> List[Dict]:
        """Fetch competitor prices using Google Shopping Light API."""
        query = f"{product_name} {category}"
        results = await self.search_shopping(query, num_results=num_results)
        return [
            {
                "title": r.title,
                "price": r.price,
                "extracted_price": r.extracted_price,
                "source": r.source,
                "link": r.link,
                "thumbnail": r.thumbnail,
                "shipping": r.shipping,
            }
            for r in results
        ]

    async def search_competitors(
        self,
        product_name: str,
        market: str = "US",
    ) -> List[SerpResult]:
        """Search for competitor products in a specific market."""
        query = f"{product_name} buy online"
        location = "United States" if market == "US" else None
        return await self.search(query, num_results=5, location=location)


# ==============================================================================
# Legacy function interface (backward compatibility)
# ==============================================================================

async def fetch_top_results(keyword: str) -> Optional[List[Dict]]:
    """Legacy function for fetching top organic SERP results."""
    q = (keyword or "").strip()
    if not q:
        return None

    if not SERP_API_KEY:
        logger.warning("[SERP] SERP_API_KEY not configured; skipping SERP fetch.")
        return None

    params = {
        "engine": "google",
        "q": q,
        "num": 3,
        "api_key": SERP_API_KEY,
    }
    timeout = httpx.Timeout(5.0)
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=ssl_verify_serp()) as client:
                resp = await client.get(SERP_API_URL, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "[SERP] non_200 status=%s attempt=%s q=%s body=%s",
                        resp.status_code, attempt + 1, q, resp.text[:200],
                    )
                    last_error = Exception(f"status_{resp.status_code}")
                    continue
                data = resp.json() or {}
                organic = data.get("organic_results") or []
                results: list[dict] = []
                for item in organic[:3]:
                    title = str(item.get("title") or "").strip()
                    snippet = str(item.get("snippet") or "").strip()
                    link = str(
                        item.get("link") or item.get("url") or ""
                    ).strip()
                    if not (title or snippet or link):
                        continue
                    results.append({"title": title, "snippet": snippet, "link": link})
                if results:
                    return results
                last_error = Exception("empty_results")
        except Exception as e:
            last_error = e
            logger.warning("[SERP] fetch_failed attempt=%s q=%s err=%s", attempt + 1, q, e)

    if last_error:
        logger.warning("[SERP] giving up after retries q=%s err=%s", q, last_error)
    return None
