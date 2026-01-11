import os
from datetime import date
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.main.core.agent_actions import run_agent_action, seasonal_campaign_agent_action


def test_run_agent_action_unknown_action_raises_400():
    with pytest.raises(HTTPException) as exc:
        run_agent_action("does_not_exist", product_data={}, context={})
    assert exc.value.status_code == 400
    assert "Unknown action" in str(exc.value.detail)


def test_social_hook_architect_fallback_happy_path(monkeypatch):
    # Force deterministic, non-OpenAI fallback
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    out = run_agent_action(
        "social_hook_architect",
        product_data={
            "title": "Ceramic Matcha Bowl",
            "category": "Kitchenware",
            "tags": ["matcha", "tea", "handmade"],
        },
        context={"focus": "Instagram Reels"},
    )

    assert "text" in out
    assert "metadata" in out
    assert out["metadata"]["instagram_create_url"].startswith("https://www.instagram.com/")
    hooks = out["metadata"]["hooks"]
    assert isinstance(hooks, list)
    assert len(hooks) == 3
    for h in hooks:
        assert "type" in h
        assert "caption" in h
        assert "hashtags" in h and isinstance(h["hashtags"], list)
        assert "copy_text" in h and isinstance(h["copy_text"], str)
        # copy_text should include caption
        assert h["caption"].strip() in h["copy_text"]


def test_social_hook_architect_openai_parsed_happy_path(monkeypatch):
    # Enable the OpenAI branch, but mock the actual call.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    fake = {
        "hooks": [
            {
                "type": "Aesthetic",
                "caption": "Soft morning light + new favorite.",
                "hashtags": ["#A", "#B", "#C"],
                "overlay": "Morning ritual",
            },
            {
                "type": "Educational",
                "caption": "3 ways to use it today.",
                "hashtags": ["#D", "#E", "#F"],
                "overlay": "3 ways",
            },
            {
                "type": "Viral",
                "caption": "POV: you can’t stop using it.",
                "hashtags": ["#G", "#H", "#I"],
                "overlay": "POV",
            },
        ],
        "overlay_suggestions": ["Overlay 1", "Overlay 2", "Overlay 3"],
    }

    with patch("src.main.core.agent_actions.openai_service.generate_json", return_value=str(fake).replace("'", '"')):
        out = run_agent_action(
            "social_hook_architect",
            product_data={"title": "Test Product", "category": "General"},
            context={"focus": "Instagram Reels"},
        )

    hooks = out["metadata"]["hooks"]
    assert len(hooks) == 3
    assert hooks[0]["type"] == "Aesthetic"
    assert out["metadata"]["overlay_suggestions"][:1] == ["Overlay 1"]


def test_seasonal_campaign_agent_within_6_weeks_shows_banner():
    # 2026 Mother's Day is 2026-05-10 (2nd Sunday of May)
    out = seasonal_campaign_agent_action(
        product_data={"category": "Skincare"},
        context={"current_date": "2026-04-10T00:00:00Z"},
    )
    assert out["metadata"]["should_show"] is True
    assert "holiday" in out["metadata"]
    assert "campaign" in out["metadata"]
    assert "discount_code_name" in out["metadata"]["campaign"]


def test_seasonal_campaign_agent_outside_6_weeks_does_not_show_banner():
    # 2026-09-15 -> next holiday is Halloween (2026-10-31), which is 46 days away (> 42)
    out = seasonal_campaign_agent_action(
        product_data={"category": "Apparel"},
        context={"current_date": "2026-09-15T00:00:00Z"},
    )
    assert out["metadata"]["should_show"] is False
    assert out["metadata"]["holiday"]["days_until"] > 42


def test_seasonal_campaign_agent_invalid_date_string_does_not_crash():
    out = seasonal_campaign_agent_action(
        product_data={"category": "General"},
        context={"current_date": "not-a-date"},
    )
    assert "metadata" in out
    assert "campaign" in out["metadata"]


