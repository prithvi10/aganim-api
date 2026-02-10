"""
Unit tests for the Template Registry system.

Tests template registration, filtering, and prompt content.
"""

import pytest

from src.main.agents.templates.registry import (
    ContentTemplate,
    TemplateInput,
    TemplateCategory,
    AgentType,
    TEMPLATE_REGISTRY,
    get_template,
    list_templates,
)


# =============================================================================
# Tests: Registration & Discovery
# =============================================================================

class TestTemplateRegistration:
    """Verify all expected templates are registered on import."""

    def test_registry_is_populated(self):
        """Templates should be registered on import of the package."""
        # Force import to trigger registration
        import src.main.agents.templates  # noqa: F401

        assert len(TEMPLATE_REGISTRY) >= 11, (
            f"Expected at least 11 templates (4 product + 7 marketing), got {len(TEMPLATE_REGISTRY)}"
        )

    # --- Product templates ---

    @pytest.mark.parametrize(
        "template_id",
        [
            "product/collection",
            "product/faq",
            "product/landing-hero",
            "product/blog-post",
        ],
    )
    def test_product_template_exists(self, template_id):
        """Every product template must be registered."""
        import src.main.agents.templates  # noqa: F401
        template = get_template(template_id)
        assert template is not None, f"Template '{template_id}' not found in registry"
        assert template.category == TemplateCategory.PRODUCT
        assert template.agent_type == AgentType.REWRITER

    # --- Marketing templates ---

    @pytest.mark.parametrize(
        "template_id",
        [
            "marketing/social-instagram",
            "marketing/email-launch",
            "marketing/email-abandoned",
            "marketing/email-welcome",
            "marketing/blog-post",
            "marketing/ad-facebook",
            "marketing/ad-google",
        ],
    )
    def test_marketing_template_exists(self, template_id):
        """Every marketing template must be registered."""
        import src.main.agents.templates  # noqa: F401
        template = get_template(template_id)
        assert template is not None, f"Template '{template_id}' not found in registry"
        assert template.category == TemplateCategory.MARKETING
        assert template.agent_type == AgentType.MARKETING


# =============================================================================
# Tests: Template Structure
# =============================================================================

class TestTemplateStructure:
    """Verify template fields are well-formed."""

    def _all_templates(self):
        import src.main.agents.templates  # noqa: F401
        return list(TEMPLATE_REGISTRY.values())

    def test_every_template_has_name_and_description(self):
        for t in self._all_templates():
            assert t.name, f"Template {t.id} missing name"
            assert t.description, f"Template {t.id} missing description"

    def test_every_template_has_inputs(self):
        """Templates should declare their required inputs."""
        for t in self._all_templates():
            assert len(t.inputs) >= 1, (
                f"Template {t.id} has no inputs defined"
            )

    def test_product_blog_post_exists(self):
        """Product blog post should be registered."""
        t = get_template("product/blog-post")
        assert t is not None

    def test_marketing_blog_post_exists(self):
        """Marketing blog post should be registered."""
        t = get_template("marketing/blog-post")
        assert t is not None


# =============================================================================
# Tests: Template Filtering
# =============================================================================

class TestTemplateFiltering:
    """Verify list_templates filtering logic."""

    def test_filter_by_product_category(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates(category=TemplateCategory.PRODUCT)
        assert all(t.category == TemplateCategory.PRODUCT for t in results)
        assert len(results) >= 4

    def test_filter_by_marketing_category(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates(category=TemplateCategory.MARKETING)
        assert all(t.category == TemplateCategory.MARKETING for t in results)
        assert len(results) >= 7

    def test_filter_by_agent_type_rewriter(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates(agent_type=AgentType.REWRITER)
        assert all(t.agent_type == AgentType.REWRITER for t in results)

    def test_filter_by_agent_type_marketing(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates(agent_type=AgentType.MARKETING)
        assert all(t.agent_type == AgentType.MARKETING for t in results)

    def test_combined_filter(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates(
            category=TemplateCategory.MARKETING,
        )
        for t in results:
            assert t.category == TemplateCategory.MARKETING

    def test_results_sorted_by_id(self):
        import src.main.agents.templates  # noqa: F401
        results = list_templates()
        ids = [t.id for t in results]
        assert ids == sorted(ids), "list_templates should return results sorted by ID"


# =============================================================================
# Tests: Prompt Content
# =============================================================================

class TestPromptContent:
    """Verify template prompts contain expected instructions."""

    def test_email_launch_prompt_asks_for_subject_and_body(self):
        t = get_template("marketing/email-launch")
        assert t is not None
        assert "subject" in t.system_prompt.lower()
        assert "body" in t.system_prompt.lower()
        assert "cta" in t.system_prompt.lower()

    def test_google_ads_prompt_enforces_char_limits(self):
        t = get_template("marketing/ad-google")
        assert t is not None
        assert "30 chars" in t.system_prompt
        assert "90 chars" in t.system_prompt

    def test_facebook_ad_prompt_enforces_char_limits(self):
        t = get_template("marketing/ad-facebook")
        assert t is not None
        assert "125 char" in t.system_prompt

    def test_faq_prompt_asks_for_json_array(self):
        t = get_template("product/faq")
        assert t is not None
        assert "faqs" in t.system_prompt.lower()
        assert "question" in t.system_prompt.lower()
        assert "answer" in t.system_prompt.lower()

    def test_landing_hero_prompt_asks_for_headline(self):
        t = get_template("product/landing-hero")
        assert t is not None
        assert "headline" in t.system_prompt.lower()
        assert "cta" in t.system_prompt.lower()

    def test_blog_post_prompt_requests_word_count(self):
        t = get_template("marketing/blog-post")
        assert t is not None
        assert "800" in t.system_prompt or "1500" in t.system_prompt

    def test_product_blog_post_prompt_requests_html(self):
        t = get_template("product/blog-post")
        assert t is not None
        assert "html" in t.system_prompt.lower()
        assert "body_html" in t.system_prompt.lower()
        assert "tags" in t.system_prompt.lower()

    def test_all_marketing_templates_return_json(self):
        """Marketing templates should request JSON output."""
        import src.main.agents.templates  # noqa: F401
        marketing_templates = list_templates(category=TemplateCategory.MARKETING)
        for t in marketing_templates:
            if t.system_prompt:  # Skip templates with empty prompts (social-instagram)
                assert "json" in t.system_prompt.lower(), (
                    f"Marketing template {t.id} should request JSON output"
                )
