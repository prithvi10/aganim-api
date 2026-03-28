"""
HTML email templates for Aganim merchant communications.

Each public function returns a ``(subject, html_body, text_body)`` tuple
ready to pass into ``email_service.send_email``.

The shared ``generate_base_email_template(content_html)`` wrapper can also
be used directly to wrap arbitrary admin-authored HTML.
"""

from __future__ import annotations

import os
from src.ecommerce.plans.entitlements import PLAN_ENTITLEMENTS

_LOGO_URL = "https://pub-2d05fd38ba8549c0811a1e0bc9426e81.r2.dev/logo/Icon-final.png"
_BRAND_COLOR = "#2563EB"
_BRAND_DARK = "#1E40AF"
_UNSUBSCRIBE_EMAIL = "unsubscribe@aganim.com"
_SUPPORT_EMAIL = "support@aganim.com"

_UI_BASE_URL = os.getenv("SHOPIFY_UI_URL", "https://aganim-ui.onrender.com")
_LANDING_URL = _UI_BASE_URL
_SUPPORT_URL = f"{_UI_BASE_URL}/support"

_FEATURE_LABELS: dict[str, str] = {
    "rewriter": "AI Product Rewriting",
    "seo": "SEO Optimisation",
    "marketing": "Marketing Copy",
    "price_scout": "Price Scout",
    "missions": "Missions",
    "image_refinement_adhoc": "Image Refinement",
    "ad_image_generation": "Ad Image Generation",
    "social_post_preview": "Social Post Preview",
    "autonomous": "Autonomous Mode",
    "publish": "One-Click Publish",
    "apply_price": "Apply Pricing",
    "meta_integration": "Meta Integration",
    "multi_locale_bulk": "Multi-Locale Bulk",
}


# ── Reusable base wrapper ──────────────────────────────────────────

def generate_base_email_template(content_html: str) -> str:
    """
    Wrap arbitrary content HTML in the branded email shell.

    Includes ``<html>``/``<head>`` boilerplate, inline CSS reset, the branded
    header with logo, a central content area, and a footer with copyright,
    support link, and List-Unsubscribe mailto.
    """
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:32px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

<!-- Header -->
<tr><td style="background-color:{_BRAND_COLOR};padding:28px 40px;text-align:center;">
  <img src="{_LOGO_URL}" alt="Aganim" width="48" height="48" style="display:inline-block;vertical-align:middle;border-radius:8px;">
  <span style="color:#ffffff;font-size:22px;font-weight:700;margin-left:12px;vertical-align:middle;">Aganim</span>
</td></tr>

<!-- Body -->
<tr><td style="padding:36px 40px;">
{content_html}
</td></tr>

<!-- Footer -->
<tr><td style="background-color:#f9fafb;padding:24px 40px;border-top:1px solid #e5e7eb;">
  <p style="margin:0 0 8px;font-size:12px;color:#6b7280;text-align:center;">
    &copy; Aganim &middot;
    <a href="{_LANDING_URL}" style="color:#6b7280;text-decoration:underline;">Aganim</a> &middot;
    <a href="{_SUPPORT_URL}" style="color:#6b7280;text-decoration:underline;">Support</a> &middot;
    <a href="mailto:{_UNSUBSCRIBE_EMAIL}?subject=Unsubscribe" style="color:#6b7280;text-decoration:underline;">Unsubscribe</a>
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# Keep backward-compatible private alias
_base_layout = generate_base_email_template


def _cta_button(label: str, url: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:28px 0;">'
        f'<tr><td style="background-color:{_BRAND_COLOR};border-radius:8px;padding:14px 32px;">'
        f'<a href="{url}" style="color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;display:inline-block;">'
        f'{label}</a></td></tr></table>'
    )


def _feature_list_html(features: dict[str, bool], *, only_true: bool = True) -> str:
    items = []
    for key, enabled in features.items():
        if only_true and not enabled:
            continue
        label = _FEATURE_LABELS.get(key, key.replace("_", " ").title())
        if isinstance(enabled, bool):
            items.append(f"<li style='margin:4px 0;color:#374151;'>{label}</li>")
        elif isinstance(enabled, int) and enabled != 0:
            items.append(f"<li style='margin:4px 0;color:#374151;'>{label}: {enabled}</li>")
    if not items:
        return ""
    return f"<ul style='padding-left:20px;margin:12px 0;'>{''.join(items)}</ul>"


def _feature_list_text(features: dict[str, bool], *, only_true: bool = True) -> str:
    lines = []
    for key, enabled in features.items():
        if only_true and not enabled:
            continue
        label = _FEATURE_LABELS.get(key, key.replace("_", " ").title())
        if isinstance(enabled, bool):
            lines.append(f"  - {label}")
        elif isinstance(enabled, int) and enabled != 0:
            lines.append(f"  - {label}: {enabled}")
    return "\n".join(lines)


# ── Template A: Welcome ────────────────────────────────────────────

def welcome_email(merchant_name: str, app_url: str = "") -> tuple[str, str, str]:
    """Welcome email sent when a merchant first installs the app."""
    subject = "Welcome to Aganim!"

    free_features = PLAN_ENTITLEMENTS["Free"]

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Welcome, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Thanks for installing Aganim. Your Free plan includes everything
  you need to get started:
</p>
{_feature_list_html(free_features)}
<p style="margin:16px 0 0;font-size:16px;color:#374151;line-height:1.6;">
  Jump in and start optimising your products for global markets.
</p>
{_cta_button("Visit Aganim", _LANDING_URL)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Need help? Visit our <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Support page</a>.
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"Welcome, {merchant_name}!\n\n"
        f"Thanks for installing Aganim. Your Free plan includes:\n"
        f"{_feature_list_text(free_features)}\n\n"
        f"Visit Aganim: {_LANDING_URL}\n"
        f"Support: {_SUPPORT_URL}\n"
    )

    return subject, html_body, text_body


# ── Template B: Plan Upgrade ───────────────────────────────────────

def plan_upgrade_email(
    merchant_name: str, plan_name: str, app_url: str = ""
) -> tuple[str, str, str]:
    """Confirmation email after upgrading to a paid plan."""
    subject = f"You've upgraded to {plan_name}!"

    plan_features = PLAN_ENTITLEMENTS.get(plan_name, {})
    free_features = PLAN_ENTITLEMENTS["Free"]
    unlocked = {
        k: v
        for k, v in plan_features.items()
        if v and v != free_features.get(k)
    }

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">You're on {plan_name} now, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Great move! Here's what you've just unlocked:
</p>
{_feature_list_html(unlocked)}
<p style="margin:16px 0 0;font-size:16px;color:#374151;line-height:1.6;">
  All your new features are ready to use right now.
</p>
{_cta_button("Visit Aganim", _LANDING_URL)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Need help? Visit our <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Support page</a>.
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"You're on {plan_name} now, {merchant_name}!\n\n"
        f"Here's what you've just unlocked:\n"
        f"{_feature_list_text(unlocked)}\n\n"
        f"Visit Aganim: {_LANDING_URL}\n"
        f"Support: {_SUPPORT_URL}\n"
    )

    return subject, html_body, text_body


# ── Template C: Credit Limit Reached ──────────────────────────────

def credit_limit_reached_email(
    merchant_name: str, plan_name: str, upgrade_url: str = ""
) -> tuple[str, str, str]:
    """Nudge email when a merchant hits their plan credit limits."""
    subject = f"You've reached your {plan_name} limits"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">You're on a roll, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  You've used all the credits available on your {plan_name} plan — that means
  you're getting real value from Aganim.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Upgrade to keep the momentum going and unlock higher limits, more
  missions, and premium features. Open Aganim from your Shopify
  admin panel to manage your plan.
</p>
{_cta_button("Visit Aganim", _LANDING_URL)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Need help? Visit our <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Support page</a>.
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"You're on a roll, {merchant_name}!\n\n"
        f"You've used all the credits available on your {plan_name} plan.\n"
        f"Upgrade to keep the momentum going.\n\n"
        f"Visit Aganim: {_LANDING_URL}\n"
        f"Support: {_SUPPORT_URL}\n"
    )

    return subject, html_body, text_body


# ── Template D: Enterprise Invite ─────────────────────────────────

def enterprise_invite_email(merchant_name: str) -> tuple[str, str, str]:
    """High-touch enterprise invitation — reply-based, no button."""
    subject = "Let's Build Your Custom Enterprise Plan"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  We've noticed your store is pushing the limits of what our standard plans
  offer — and that's exciting.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  We'd love to put together a custom Enterprise package tailored to your
  volume and workflow. Think dedicated support, unlimited missions, and
  priority processing.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;font-weight:600;">
  Simply reply to this email and we'll set up a quick call.
</p>
{_cta_button("Visit Aganim", _LANDING_URL)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Need help? Visit our <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Support page</a>.
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"Hi {merchant_name},\n\n"
        f"We've noticed your store is pushing the limits of what our standard "
        f"plans offer — and that's exciting.\n\n"
        f"We'd love to put together a custom Enterprise package tailored to "
        f"your volume and workflow.\n\n"
        f"Simply reply to this email and we'll set up a quick call.\n\n"
        f"Visit Aganim: {_LANDING_URL}\n"
        f"Support: {_SUPPORT_URL}\n"
    )

    return subject, html_body, text_body


# ── Template E: Feedback Request ──────────────────────────────────

def feedback_email(merchant_name: str, feedback_link: str = "") -> tuple[str, str, str]:
    """Ask a merchant to share their experience via the support page."""
    subject = "We'd love your feedback on Aganim"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  You've been using Aganim and we'd love to hear what you think.
  Your feedback helps us build the features that matter most to merchants
  like you.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  It takes less than 2 minutes and makes a real difference. Visit our
  support page to share your thoughts.
</p>
{_cta_button("Share Your Feedback", _SUPPORT_URL)}
<p style="margin:16px 0 0;font-size:14px;color:#6b7280;">
  Thank you for helping us improve! &middot;
  <a href="{_LANDING_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Aganim</a>
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"Hi {merchant_name},\n\n"
        f"You've been using Aganim and we'd love to hear what "
        f"you think. Your feedback helps us build the features that matter "
        f"most.\n\n"
        f"Share your feedback: {_SUPPORT_URL}\n\n"
        f"Thank you for helping us improve!\n"
        f"Visit Aganim: {_LANDING_URL}\n"
    )

    return subject, html_body, text_body


# ── Template F: App Store Rating ──────────────────────────────────

def rating_email(merchant_name: str, app_store_review_link: str = "") -> tuple[str, str, str]:
    """Ask a merchant to leave a review on the Shopify App Store."""
    subject = "Enjoying Aganim? We'd love to hear from you!"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  We hope Aganim has been helping your store reach new markets.
  If you've had a positive experience, we'd really appreciate hearing
  about it.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Visit our support page to share your thoughts, or simply reply to this
  email — it means the world to us.
</p>
{_cta_button("Visit Aganim", _LANDING_URL)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Need help? Visit our <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;">Support page</a>.
</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"Hi {merchant_name},\n\n"
        f"We hope Aganim has been helping your store reach new "
        f"markets. If you've had a positive experience, we'd really "
        f"appreciate hearing about it.\n\n"
        f"Visit Aganim: {_LANDING_URL}\n"
        f"Support: {_SUPPORT_URL}\n"
    )

    return subject, html_body, text_body


# ── Template G: Custom Admin Email ────────────────────────────────

def custom_admin_email(custom_html_body: str) -> tuple[str, str, str]:
    """
    Wrap admin-authored HTML in the branded template.

    Subject is not set here — the caller provides it separately.
    Returns an empty subject so the caller can override it.
    """
    html_body = generate_base_email_template(custom_html_body)

    import re
    text_body = re.sub(r"<[^>]+>", "", custom_html_body)
    text_body = re.sub(r"\s+", " ", text_body).strip()

    return "", html_body, text_body


# ── Dispatcher ──────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, callable] = {
    "welcome": welcome_email,
    "upgrade": plan_upgrade_email,
    "credit_limit": credit_limit_reached_email,
    "enterprise": enterprise_invite_email,
    "feedback": feedback_email,
    "rating": rating_email,
    "custom": custom_admin_email,
}
