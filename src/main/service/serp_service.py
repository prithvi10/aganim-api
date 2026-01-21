import httpx
from typing import Optional, List, Dict
from src.main.logging.logger import get_logger
from src.main.config.configs import SERP_API_KEY, SERP_API_URL

logger = get_logger(__name__)

async def fetch_top_results(keyword: str) -> Optional[List[Dict]]:
    """
    Fetch top organic SERP results for a keyword.
    Returns a list of dicts: [{title, snippet, link}] or None on failure.
    """
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
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(SERP_API_URL, params=params)
                if resp.status_code != 200:
                    logger.warning("[SERP] non_200 status=%s attempt=%s q=%s body=%s", resp.status_code, attempt + 1, q, resp.text[:200])
                    last_error = Exception(f"status_{resp.status_code}")
                    continue
                data = resp.json() or {}
                organic = data.get("organic_results") or []
                results: list[dict] = []
                for item in organic[:3]:
                    title = str(item.get("title") or "").strip()
                    snippet = str(item.get("snippet") or "").strip()
                    link = str(
                        item.get("link")  # SerpAPI primary field
                        or item.get("url")  # fallback field name (defensive)
                        or ""
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
