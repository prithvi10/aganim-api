"""Unit tests for BulkMissionRequest and BulkMissionPreferences Pydantic models."""

import pytest
from pydantic import ValidationError
from src.ecommerce.api.models import BulkMissionRequest, BulkMissionPreferences


class TestBulkMissionPreferences:
    def test_defaults(self):
        prefs = BulkMissionPreferences()
        assert prefs.tone_profile == "professional"
        assert prefs.brand_soul_enabled is False
        assert prefs.us_units_conversion is True
        assert prefs.target_market == "en"

    def test_custom_values(self):
        prefs = BulkMissionPreferences(
            tone_profile="luxury",
            brand_soul_enabled=True,
            us_units_conversion=False,
            target_market="zh-TW",
        )
        assert prefs.tone_profile == "luxury"
        assert prefs.brand_soul_enabled is True
        assert prefs.us_units_conversion is False
        assert prefs.target_market == "zh-TW"

    def test_invalid_tone(self):
        with pytest.raises(ValidationError):
            BulkMissionPreferences(tone_profile="aggressive")


class TestBulkMissionRequest:
    def test_valid_text_only(self):
        req = BulkMissionRequest(
            mission_type="text_only",
            preferences=BulkMissionPreferences(),
        )
        assert req.mission_type == "text_only"
        assert req.preferences.tone_profile == "professional"

    def test_valid_full_launch(self):
        req = BulkMissionRequest(
            mission_type="full_launch",
            preferences=BulkMissionPreferences(tone_profile="minimalist"),
        )
        assert req.mission_type == "full_launch"
        assert req.preferences.tone_profile == "minimalist"

    def test_invalid_mission_type(self):
        with pytest.raises(ValidationError):
            BulkMissionRequest(
                mission_type="unknown",
                preferences=BulkMissionPreferences(),
            )

    def test_missing_preferences(self):
        with pytest.raises(ValidationError):
            BulkMissionRequest(mission_type="text_only")
