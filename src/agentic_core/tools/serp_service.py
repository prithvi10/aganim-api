"""
SerpService - Search Engine Results Page service for competitor analysis.

Provides structured SERP data for agents like PriceScoutAgent.
"""
from __future__ import annotations

import os
import re as _re
from typing import Optional, List, Dict
from dataclasses import dataclass
import httpx

from src.shared.logging.logger import get_logger
from src.shared.config.configs import SERP_API_KEY, SERP_API_URL
from src.shared.utils.httpx_verify import ssl_verify_serp


_QUERY_NOISE_RE = _re.compile(
    r"[【】\[\]（）\(\)★☆♪※◎●○■□▲△▼▽♦◆〇×＊／/\u2600-\u26FF\u2700-\u27BF]"
)
_MULTI_SPACE_RE = _re.compile(r"\s{2,}")
_TRAILING_PUNCT_RE = _re.compile(r"[！!？?、。,.\-–—:：;；\s]+$")
_LEADING_PUNCT_RE = _re.compile(r"^[！!？?、。,.\-–—:：;；/\s]+")

_JA_NOISE_PHRASES_RE = _re.compile(
    r"ふるさと納税|大ボリューム|送料無料|送料込み?|ポイント\d+倍"
    r"|離島.{0,6}配送不可|沖縄.{0,6}配送不可|北海道.{0,6}配送不可"
    r"|あす楽|即日発送|翌日配送|ネコポス|メール便"
    r"|画像はイメージ|お早めに|賞味期限|消費期限|保存方法"
    r"|寄附申込み.{0,10}キャンセル|返礼品の変更|よくある質問"
    r"|共通返礼品|配送方法|製造者|提供元|配送不可地域"
    r"|お選びください|こちらの.{0,10}返礼品",
    _re.IGNORECASE,
)

_MAX_SERP_QUERY_LEN = 80


def _sanitize_serp_query(raw: str) -> str:
    """Strip marketing / logistics noise from product titles for SERP API.

    Japanese product names from Shopify/Rakuten often contain brackets,
    decorative symbols, logistics disclaimers, and ふるさと納税 boilerplate
    that cause Google Shopping to return zero results.
    """
    q = _QUERY_NOISE_RE.sub(" ", raw)
    q = _JA_NOISE_PHRASES_RE.sub(" ", q)
    q = _MULTI_SPACE_RE.sub(" ", q)
    q = _LEADING_PUNCT_RE.sub("", q)
    q = _TRAILING_PUNCT_RE.sub("", q)
    q = q.strip()
    if len(q) > _MAX_SERP_QUERY_LEN:
        q = q[:_MAX_SERP_QUERY_LEN].rsplit(" ", 1)[0].strip()
        q = _TRAILING_PUNCT_RE.sub("", q)
    return q

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
        self.timeout = httpx.Timeout(15.0)

    @staticmethod
    def _currency_symbol(gl: Optional[str]) -> str:
        return {"jp": "¥", "kr": "₩", "tw": "NT$", "cn": "¥", "th": "฿"}.get(gl or "", "$")

    async def search(
        self,
        query: str,
        num_results: int = 3,
        engine: str = "google",
        location: Optional[str] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        google_domain: Optional[str] = None,
    ) -> List[SerpResult]:
        """
        Fetch top organic SERP results for a query.

        Args:
            query: Search query string
            num_results: Number of results to return (default: 3)
            engine: Search engine to use (default: google)
            location: Optional location for localized results
            gl: Google country code (e.g. "us", "de", "fr")
            hl: Google language code (e.g. "en", "de", "fr")
            google_domain: Google domain to use (e.g. "google.co.jp")

        Returns:
            List of SerpResult objects, empty list on failure
        """
        q = _sanitize_serp_query(query or "")
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
        if gl:
            params["gl"] = gl
        if hl:
            params["hl"] = hl
        if google_domain:
            params["google_domain"] = google_domain

        for attempt in range(3):
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
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        google_domain: Optional[str] = None,
    ) -> List[ShoppingResult]:
        """
        Fetch Google Shopping results for a product query.

        Tries ``google_shopping_light`` first (cheaper).  If that returns no
        results after 3 attempts, falls back to the full ``google_shopping``
        engine which has better international coverage.
        """
        q = _sanitize_serp_query(query or "")
        if not q:
            return []

        if not self.api_key:
            logger.warning("[SERP] API key not configured; skipping shopping search")
            return []

        logger.info(
            "[SERP] shopping query=%s gl=%s hl=%s location=%s domain=%s",
            q[:60], gl, hl, location, google_domain,
        )

        currency = self._currency_symbol(gl)

        base_params: dict = {
            "q": q,
            "num": num_results,
            "api_key": self.api_key,
        }
        if location:
            base_params["location"] = location
        if gl:
            base_params["gl"] = gl
        if hl:
            base_params["hl"] = hl
        if google_domain:
            base_params["google_domain"] = google_domain

        shopping_timeout = httpx.Timeout(30.0)

        engines = [
            ("google_shopping_light", 3),
            ("google_shopping", 1),
        ]

        for engine, max_attempts in engines:
            params = {**base_params, "engine": engine}
            for attempt in range(max_attempts):
                try:
                    async with httpx.AsyncClient(
                        timeout=shopping_timeout,
                        verify=ssl_verify_serp(),
                    ) as client:
                        resp = await client.get(self.api_url, params=params)

                        if resp.status_code != 200:
                            logger.warning(
                                "[SERP] %s non_200 status=%s attempt=%s q=%s body=%s",
                                engine,
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
                                    cleaned = (
                                        price_str
                                        .replace("$", "")
                                        .replace("¥", "")
                                        .replace("￥", "")
                                        .replace("円", "")
                                        .replace(",", "")
                                        .strip()
                                    )
                                    extracted_price = float(cleaned) if cleaned else None
                                except (ValueError, TypeError):
                                    extracted_price = None

                            if extracted_price is None or extracted_price <= 0:
                                continue

                            price = str(item.get("price") or f"{currency}{extracted_price:,.0f}" if extracted_price >= 1000 else item.get("price") or f"{currency}{extracted_price:.2f}")
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
                                "[SERP] %s query=%s results=%s (filtered from %s)",
                                engine,
                                q[:30],
                                len(results),
                                len(shopping_results),
                            )
                            return results

                except Exception as e:
                    logger.warning(
                        "[SERP] %s fetch_failed attempt=%s q=%s err=%s",
                        engine,
                        attempt + 1,
                        q[:30],
                        e,
                    )

        logger.warning("[SERP] shopping giving up after all engines q=%s", q[:30])
        return []

    async def get_competitor_prices(
        self,
        product_name: str,
        category: str,
        num_results: int = 20,
        location: Optional[str] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        google_domain: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch competitor prices using Google Shopping API.

        Tries the full product name first.  If zero results, retries with a
        simplified query (first few meaningful words + category) to catch
        broader matches.
        """
        cat = (category or "").strip()
        cat_suffix = f" {cat}" if cat and cat.lower() != "general" else ""

        query = f"{product_name}{cat_suffix}"
        results = await self.search_shopping(
            query,
            num_results=num_results,
            location=location or "United States",
            gl=gl,
            hl=hl,
            google_domain=google_domain,
        )

        if not results:
            short_name = " ".join(product_name.split()[:4])
            fallback_query = f"{short_name}{cat_suffix}"
            if _sanitize_serp_query(fallback_query) != _sanitize_serp_query(query):
                logger.info("[SERP] retrying with shorter query: %s", fallback_query[:40])
                results = await self.search_shopping(
                    fallback_query,
                    num_results=num_results,
                    location=location or "United States",
                    gl=gl,
                    hl=hl,
                    google_domain=google_domain,
                )

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
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        location: Optional[str] = None,
        google_domain: Optional[str] = None,
    ) -> List[SerpResult]:
        """Search for competitor products in a specific market."""
        query = f"{product_name} buy online"
        loc = location or ("United States" if market == "US" else None)
        return await self.search(query, num_results=5, location=loc, gl=gl, hl=hl, google_domain=google_domain)


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
