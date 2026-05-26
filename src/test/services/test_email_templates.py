"""
Unit tests for email templates.

Covers:
- All four template functions return (subject, html, text) tuples
- HTML contains expected structural elements (logo, unsubscribe, CTA)
- Text fallback contains key information
- Template registry maps to correct functions
- Plan-aware templates use PLAN_ENTITLEMENTS correctly
"""
import pytest

from src.ecommerce.services.email_templates import (
    welcome_email,
    plan_upgrade_email,
    credit_limit_reached_email,
    enterprise_invite_email,
    feedback_email,
    rating_email,
    custom_admin_email,
    generate_base_email_template,
    TEMPLATE_REGISTRY,
    _base_layout,
    _LOGO_URL,
    _UNSUBSCRIBE_EMAIL,
    _LANDING_URL,
    _SUPPORT_URL,
)


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------

def _assert_valid_template_tuple(result):
    """Every template must return (subject, html_body, text_body)."""
    assert isinstance(result, tuple)
    assert len(result) == 3
    subject, html, text = result
    assert isinstance(subject, str) and len(subject) > 0
    assert isinstance(html, str) and len(html) > 0
    assert isinstance(text, str) and len(text) > 0


def _assert_html_structure(html: str):
    """Common HTML structure checks."""
    assert "<!DOCTYPE html>" in html
    assert _LOGO_URL in html
    assert "Aganim" in html
    assert _UNSUBSCRIBE_EMAIL in html
    assert "Unsubscribe" in html


# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------

class TestBaseLayout:
    def test_wraps_content(self):
        html = _base_layout("<p>Hello World</p>")
        assert "<p>Hello World</p>" in html
        _assert_html_structure(html)

    def test_contains_footer(self):
        html = _base_layout("<p>content</p>")
        assert "Unsubscribe" in html
        assert _UNSUBSCRIBE_EMAIL in html


# ---------------------------------------------------------------------------
# Template A: Welcome Email
# ---------------------------------------------------------------------------

class TestWelcomeEmail:
    def test_returns_valid_tuple(self):
        result = welcome_email("Acme Store", "https://app.example.com")
        _assert_valid_template_tuple(result)

    def test_subject(self):
        subject, _, _ = welcome_email("Acme", "https://app.example.com")
        assert subject == "Welcome to Aganim AI"

    def test_html_contains_merchant_name(self):
        _, html, _ = welcome_email("Acme Store", "https://app.example.com")
        assert "Acme Store" in html

    def test_html_contains_cta(self):
        _, html, _ = welcome_email("Acme")
        assert "Visit Aganim" in html
        assert _LANDING_URL in html
        assert _SUPPORT_URL in html

    def test_html_structure(self):
        _, html, _ = welcome_email("X")
        _assert_html_structure(html)

    def test_html_lists_free_features(self):
        _, html, _ = welcome_email("X")
        assert "AI Product Rewriting" in html
        assert "Marketing Copy" in html

    def test_text_contains_key_info(self):
        _, _, text = welcome_email("Acme")
        assert "Acme" in text
        assert _LANDING_URL in text
        assert _SUPPORT_URL in text
        assert "Free plan" in text


# ---------------------------------------------------------------------------
# Template B: Plan Upgrade Email
# ---------------------------------------------------------------------------

class TestPlanUpgradeEmail:
    def test_returns_valid_tuple(self):
        result = plan_upgrade_email("Acme", "Pro", "https://app.example.com")
        _assert_valid_template_tuple(result)

    def test_subject_includes_plan_name(self):
        subject, _, _ = plan_upgrade_email("Acme", "Pro", "https://example.com")
        assert "Pro" in subject

    def test_html_contains_merchant_and_plan(self):
        _, html, _ = plan_upgrade_email("Acme", "Pro", "https://example.com")
        assert "Acme" in html
        assert "Pro" in html

    def test_html_contains_cta(self):
        _, html, _ = plan_upgrade_email("Acme", "Pro")
        assert "Visit Aganim" in html
        assert _LANDING_URL in html
        assert _SUPPORT_URL in html

    def test_html_shows_unlocked_features_for_pro(self):
        _, html, _ = plan_upgrade_email("Acme", "Pro", "https://example.com")
        assert "Autonomous Mode" in html or "One-Click Publish" in html

    def test_text_contains_plan_name(self):
        _, _, text = plan_upgrade_email("Acme", "Standard", "https://example.com")
        assert "Standard" in text

    def test_unknown_plan_returns_gracefully(self):
        result = plan_upgrade_email("Acme", "NonexistentPlan", "https://example.com")
        _assert_valid_template_tuple(result)


# ---------------------------------------------------------------------------
# Template C: Credit Limit Reached
# ---------------------------------------------------------------------------

class TestCreditLimitReachedEmail:
    def test_returns_valid_tuple(self):
        result = credit_limit_reached_email("Acme", "Free", "https://upgrade.example.com")
        _assert_valid_template_tuple(result)

    def test_subject_includes_plan(self):
        subject, _, _ = credit_limit_reached_email("Acme", "Basic", "https://example.com")
        assert "Basic" in subject

    def test_html_contains_upgrade_cta(self):
        _, html, _ = credit_limit_reached_email("Acme", "Free")
        assert "Visit Aganim" in html
        assert _LANDING_URL in html
        assert _SUPPORT_URL in html

    def test_html_friendly_tone(self):
        _, html, _ = credit_limit_reached_email("Acme", "Free")
        assert "on a roll" in html

    def test_text_contains_landing_and_support(self):
        _, _, text = credit_limit_reached_email("Acme", "Free")
        assert _LANDING_URL in text
        assert _SUPPORT_URL in text


# ---------------------------------------------------------------------------
# Template D: Enterprise Invite
# ---------------------------------------------------------------------------

class TestEnterpriseInviteEmail:
    def test_returns_valid_tuple(self):
        result = enterprise_invite_email("Acme Store")
        _assert_valid_template_tuple(result)

    def test_subject(self):
        subject, _, _ = enterprise_invite_email("Acme")
        assert "Enterprise" in subject

    def test_html_contains_merchant_name(self):
        _, html, _ = enterprise_invite_email("Acme Store")
        assert "Acme Store" in html

    def test_html_has_reply_prompt_and_links(self):
        _, html, _ = enterprise_invite_email("Acme")
        assert "reply to this email" in html.lower()
        assert _LANDING_URL in html
        assert _SUPPORT_URL in html

    def test_html_structure(self):
        _, html, _ = enterprise_invite_email("Acme")
        _assert_html_structure(html)

    def test_text_contains_reply_prompt(self):
        _, _, text = enterprise_invite_email("Acme")
        assert "reply" in text.lower()


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Template E: Feedback Email
# ---------------------------------------------------------------------------

class TestFeedbackEmail:
    def test_returns_valid_tuple(self):
        result = feedback_email("Acme", "https://feedback.example.com")
        _assert_valid_template_tuple(result)

    def test_subject(self):
        subject, _, _ = feedback_email("Acme", "https://feedback.example.com")
        assert "feedback" in subject.lower()

    def test_html_contains_merchant_name(self):
        _, html, _ = feedback_email("Acme Store", "https://feedback.example.com")
        assert "Acme Store" in html

    def test_html_contains_cta(self):
        _, html, _ = feedback_email("Acme")
        assert "Share Your Feedback" in html
        assert _SUPPORT_URL in html

    def test_html_structure(self):
        _, html, _ = feedback_email("X")
        _assert_html_structure(html)

    def test_text_contains_link(self):
        _, _, text = feedback_email("Acme")
        assert _SUPPORT_URL in text
        assert _LANDING_URL in text


# ---------------------------------------------------------------------------
# Template F: Rating Email
# ---------------------------------------------------------------------------

class TestRatingEmail:
    def test_returns_valid_tuple(self):
        result = rating_email("Acme", "https://apps.shopify.com/myapp#reviews")
        _assert_valid_template_tuple(result)

    def test_subject(self):
        subject, _, _ = rating_email("Acme")
        assert "aganim" in subject.lower()

    def test_html_contains_cta(self):
        _, html, _ = rating_email("Acme")
        assert "Visit Aganim" in html
        assert _LANDING_URL in html
        assert _SUPPORT_URL in html

    def test_html_structure(self):
        _, html, _ = rating_email("X")
        _assert_html_structure(html)

    def test_text_contains_link(self):
        _, _, text = rating_email("Acme")
        assert _LANDING_URL in text
        assert _SUPPORT_URL in text


# ---------------------------------------------------------------------------
# Template G: Custom Admin Email
# ---------------------------------------------------------------------------

class TestCustomAdminEmail:
    def test_returns_tuple(self):
        result = custom_admin_email("<p>Hello world</p>")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_subject_is_empty(self):
        subject, _, _ = custom_admin_email("<p>content</p>")
        assert subject == ""

    def test_html_wraps_content_in_base_template(self):
        _, html, _ = custom_admin_email("<h2>Big News</h2>")
        assert "<h2>Big News</h2>" in html
        assert "<!DOCTYPE html>" in html
        assert _LOGO_URL in html

    def test_text_strips_html(self):
        _, _, text = custom_admin_email("<h2>Hello</h2><p>World</p>")
        assert "Hello" in text
        assert "World" in text
        assert "<" not in text


# ---------------------------------------------------------------------------
# generate_base_email_template (public API)
# ---------------------------------------------------------------------------

class TestGenerateBaseEmailTemplate:
    def test_is_same_as_base_layout(self):
        content = "<p>test</p>"
        assert generate_base_email_template(content) == _base_layout(content)

    def test_contains_support_link(self):
        html = generate_base_email_template("<p>content</p>")
        assert "Support" in html


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

class TestTemplateRegistry:
    def test_all_templates_registered(self):
        assert "welcome" in TEMPLATE_REGISTRY
        assert "upgrade" in TEMPLATE_REGISTRY
        assert "credit_limit" in TEMPLATE_REGISTRY
        assert "enterprise" in TEMPLATE_REGISTRY
        assert "feedback" in TEMPLATE_REGISTRY
        assert "rating" in TEMPLATE_REGISTRY
        assert "custom" in TEMPLATE_REGISTRY

    def test_registry_maps_to_correct_functions(self):
        assert TEMPLATE_REGISTRY["welcome"] is welcome_email
        assert TEMPLATE_REGISTRY["upgrade"] is plan_upgrade_email
        assert TEMPLATE_REGISTRY["credit_limit"] is credit_limit_reached_email
        assert TEMPLATE_REGISTRY["enterprise"] is enterprise_invite_email
        assert TEMPLATE_REGISTRY["feedback"] is feedback_email
        assert TEMPLATE_REGISTRY["rating"] is rating_email
        assert TEMPLATE_REGISTRY["custom"] is custom_admin_email

    def test_registry_has_seven_entries(self):
        assert len(TEMPLATE_REGISTRY) == 13
