"""
HTML email templates for CrossBorderAgent merchant communications.

Each public function returns a ``(subject, html_body, text_body)`` tuple
ready to pass into ``email_service.send_email``.
"""

from __future__ import annotations

from src.ecommerce.plans.entitlements import PLAN_ENTITLEMENTS

_LOGO_URL = "https://pub-2d05fd38ba8549c0811a1e0bc9426e81.r2.dev/logo/Icon-final.png"
_BRAND_COLOR = "#2563EB"
_BRAND_DARK = "#1E40AF"
_UNSUBSCRIBE_EMAIL = "unsubscribe@crossborderagent.com"

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


def _base_layout(content_html: str) -> str:
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
  <img src="{_LOGO_URL}" alt="CrossBorderAgent" width="48" height="48" style="display:inline-block;vertical-align:middle;border-radius:8px;">
  <span style="color:#ffffff;font-size:22px;font-weight:700;margin-left:12px;vertical-align:middle;">CrossBorderAgent</span>
</td></tr>

<!-- Body -->
<tr><td style="padding:36px 40px;">
{content_html}
</td></tr>

<!-- Footer -->
<tr><td style="background-color:#f9fafb;padding:24px 40px;border-top:1px solid #e5e7eb;">
  <p style="margin:0;font-size:12px;color:#6b7280;text-align:center;">
    &copy; CrossBorderAgent &middot;
    <a href="mailto:{_UNSUBSCRIBE_EMAIL}?subject=Unsubscribe" style="color:#6b7280;text-decoration:underline;">Unsubscribe</a>
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


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


# ── Template A ──────────────────────────────────────────────────────

def welcome_email(merchant_name: str, app_url: str) -> tuple[str, str, str]:
    """Welcome email sent when a merchant first installs the app."""
    subject = "Welcome to CrossBorderAgent!"

    free_features = PLAN_ENTITLEMENTS["Free"]

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Welcome, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Thanks for installing CrossBorderAgent. Your Free plan includes everything
  you need to get started:
</p>
{_feature_list_html(free_features)}
<p style="margin:16px 0 0;font-size:16px;color:#374151;line-height:1.6;">
  Jump in and start optimising your products for global markets.
</p>
{_cta_button("Get Started", app_url)}"""

    html_body = _base_layout(content)

    text_body = (
        f"Welcome, {merchant_name}!\n\n"
        f"Thanks for installing CrossBorderAgent. Your Free plan includes:\n"
        f"{_feature_list_text(free_features)}\n\n"
        f"Get started: {app_url}\n"
    )

    return subject, html_body, text_body


# ── Template B ──────────────────────────────────────────────────────

def plan_upgrade_email(
    merchant_name: str, plan_name: str, app_url: str
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
{_cta_button("Explore Your New Features", app_url)}"""

    html_body = _base_layout(content)

    text_body = (
        f"You're on {plan_name} now, {merchant_name}!\n\n"
        f"Here's what you've just unlocked:\n"
        f"{_feature_list_text(unlocked)}\n\n"
        f"Explore your features: {app_url}\n"
    )

    return subject, html_body, text_body


# ── Template C ──────────────────────────────────────────────────────

def credit_limit_reached_email(
    merchant_name: str, plan_name: str, upgrade_url: str
) -> tuple[str, str, str]:
    """Nudge email when a merchant hits their plan credit limits."""
    subject = f"You've reached your {plan_name} limits"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">You're on a roll, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  You've used all the credits available on your {plan_name} plan — that means
  you're getting real value from CrossBorderAgent.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Upgrade to keep the momentum going and unlock higher limits, more
  missions, and premium features.
</p>
{_cta_button("Upgrade Plan", upgrade_url)}"""

    html_body = _base_layout(content)

    text_body = (
        f"You're on a roll, {merchant_name}!\n\n"
        f"You've used all the credits available on your {plan_name} plan.\n"
        f"Upgrade to keep the momentum going: {upgrade_url}\n"
    )

    return subject, html_body, text_body


# ── Template D ──────────────────────────────────────────────────────

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
<p style="margin:24px 0 0;font-size:14px;color:#6b7280;">— The CrossBorderAgent Team</p>"""

    html_body = _base_layout(content)

    text_body = (
        f"Hi {merchant_name},\n\n"
        f"We've noticed your store is pushing the limits of what our standard "
        f"plans offer — and that's exciting.\n\n"
        f"We'd love to put together a custom Enterprise package tailored to "
        f"your volume and workflow.\n\n"
        f"Simply reply to this email and we'll set up a quick call.\n\n"
        f"— The CrossBorderAgent Team\n"
    )

    return subject, html_body, text_body


# ── Dispatcher ──────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, callable] = {
    "welcome": welcome_email,
    "upgrade": plan_upgrade_email,
    "credit_limit": credit_limit_reached_email,
    "enterprise": enterprise_invite_email,
}
