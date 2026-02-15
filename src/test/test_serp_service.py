import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agentic_core.tools import serp_service


@pytest.mark.asyncio
async def test_fetch_top_results_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "organic_results": [
            {"title": "A", "snippet": "S1", "link": "https://a.example"},
            {"title": "B", "snippet": "S2", "link": "https://b.example"},
            {"title": "C", "snippet": "S3", "link": "https://c.example"},
            {"title": "D", "snippet": "S4", "link": "https://d.example"},
        ]
    }

    with patch("src.agentic_core.tools.serp_service.SERP_API_KEY", "key"), \
         patch("src.agentic_core.tools.serp_service.SERP_API_URL", "https://serpapi.com/search"), \
         patch("src.agentic_core.tools.serp_service.httpx.AsyncClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_resp)

        results = await serp_service.fetch_top_results("matcha tea")

        assert results is not None
        assert len(results) == 3
        assert results[0]["title"] == "A"
        assert results[1]["link"] == "https://b.example"
        assert results[2]["snippet"] == "S3"


@pytest.mark.asyncio
async def test_fetch_top_results_no_api_key():
    with patch("src.agentic_core.tools.serp_service.SERP_API_KEY", ""), \
         patch("src.agentic_core.tools.serp_service.httpx.AsyncClient") as MockClient:
        results = await serp_service.fetch_top_results("matcha tea")
        assert results is None
        assert not MockClient.called


@pytest.mark.asyncio
async def test_fetch_top_results_timeout_or_error_returns_none():
    with patch("src.agentic_core.tools.serp_service.SERP_API_KEY", "key"), \
         patch("src.agentic_core.tools.serp_service.httpx.AsyncClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))

        results = await serp_service.fetch_top_results("matcha tea")
        assert results is None


@pytest.mark.asyncio
async def test_fetch_top_results_non_200_returns_none():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "error"
    with patch("src.agentic_core.tools.serp_service.SERP_API_KEY", "key"), \
         patch("src.agentic_core.tools.serp_service.SERP_API_URL", "https://serpapi.com/search"), \
         patch("src.agentic_core.tools.serp_service.httpx.AsyncClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_resp)

        results = await serp_service.fetch_top_results("matcha tea")
        assert results is None
