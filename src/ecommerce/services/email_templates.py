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
    subject = "Welcome to Aganim AI"

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
    "beta_invite": lambda name, **kw: beta_invite_email(name),
    "beta_welcome": lambda name, **kw: beta_welcome_email(name),
    "beta_checkin": lambda name, **kw: beta_checkin_email(name),
    "beta_feedback": lambda name, **kw: beta_feedback_request_email(name),
    "beta_exit": lambda name, **kw: beta_exit_email(name),
}


# ── Beta Templates ────────────────────────────────────────────────

_INSTALL_URL = "https://admin.shopify.com/oauth/install?client_id=315cfaf63c9baf27e4ba9a22b91b168e"


def beta_invite_email(merchant_name: str, signup_url: str = "") -> tuple[str, str, str]:
    """Cold outreach to invite a merchant into the closed beta."""
    subject = "Invitation: Free Beta Access to Aganim AI"

    cta_url = signup_url or _INSTALL_URL
    cta_label = "Sign Up for Beta" if signup_url else "Join the Beta"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  We're inviting a small group of merchants to beta test <strong>Aganim AI</strong> —
  an AI tool that rewrites product pages into sales-grade copy for global markets,
  optimises SEO, and generates marketing visuals.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  As a beta tester you get <strong>full Pro access to all features — completely free
  for 6 weeks</strong>, no commitment. In return, we'd love your honest feedback on the experience.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Setup takes less than 5 minutes. Interested?
</p>
{_cta_button(cta_label, cta_url)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  Simply reply to this email if you have questions. We'd love to have you!
</p>"""

    html_body = _base_layout(content)
    text_body = (
        f"Hi {merchant_name},\n\n"
        f"We're inviting a small group of merchants to beta test Aganim AI.\n"
        f"Full Pro access, completely free for 6 weeks, no commitment.\n\n"
        f"Sign up: {cta_url}\n\n"
        f"Reply to this email if you have questions.\n"
    )
    return subject, html_body, text_body


def beta_welcome_email(merchant_name: str) -> tuple[str, str, str]:
    """Welcome email sent when a beta merchant installs the app."""
    subject = "Welcome to the Aganim AI Beta!"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Welcome to the Beta, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  You now have <strong>full, unlimited access</strong> to every Aganim feature —
  product rewriting, SEO optimisation, marketing copy, image generation, and more.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>Here's how to get started:</strong>
</p>
<ol style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>Open Aganim from your Shopify admin panel</li>
  <li>Complete the Brand Soul wizard (2 minutes)</li>
  <li>Try rewriting your best-selling product</li>
</ol>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  I'll check in with you in a week to see how things are going. If you need
  anything at all, just reply to this email.
</p>
{_cta_button("Open Aganim", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"Welcome to the Beta, {merchant_name}!\n\n"
        f"You now have full unlimited access to every Aganim feature.\n\n"
        f"Get started:\n"
        f"1. Open Aganim from your Shopify admin panel\n"
        f"2. Complete the Brand Soul wizard\n"
        f"3. Try rewriting your best-selling product\n\n"
        f"Open Aganim: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body


def beta_checkin_email(merchant_name: str) -> tuple[str, str, str]:
    """Weekly check-in nudge for beta merchants."""
    subject = "How's your Aganim experience going?"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Just checking in on your beta experience. Have you had a chance to try
  the AI rewriter on your products?
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>Quick tip:</strong> Try the SEO Optimizer on your best-selling product —
  it analyses Google SERP data for your target market and suggests title/meta
  improvements that can boost organic traffic.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  If anything isn't working right, or you have ideas for improvement, just
  reply to this email. Your feedback shapes what we build next.
</p>
{_cta_button("Open Aganim", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"Hi {merchant_name},\n\n"
        f"Just checking in on your beta experience.\n\n"
        f"Quick tip: Try the SEO Optimizer on your best-selling product.\n\n"
        f"Reply to this email with any feedback or issues.\n"
        f"Open Aganim: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body


def beta_feedback_request_email(merchant_name: str) -> tuple[str, str, str]:
    """Structured feedback request for beta merchants."""
    subject = "Quick feedback on Aganim (2 minutes)"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Hi {merchant_name},</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  You've been using Aganim for a while now and we'd love to hear what you think.
  Your feedback directly shapes our roadmap.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>3 quick questions:</strong>
</p>
<ol style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>What feature has been most valuable to you?</li>
  <li>What's your biggest frustration?</li>
  <li>Would you pay for this tool after the beta ends?</li>
</ol>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Simply reply to this email with your answers — even a few words helps
  enormously. Thank you!
</p>
{_cta_button("Visit Support Page", _SUPPORT_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"Hi {merchant_name},\n\n"
        f"We'd love your feedback on Aganim (takes 2 minutes).\n\n"
        f"3 quick questions:\n"
        f"1. What feature has been most valuable to you?\n"
        f"2. What's your biggest frustration?\n"
        f"3. Would you pay for this tool after the beta ends?\n\n"
        f"Reply to this email with your answers.\n"
        f"Support: {_SUPPORT_URL}\n"
    )
    return subject, html_body, text_body


def beta_exit_email(merchant_name: str) -> tuple[str, str, str]:
    """Thank you / exit email at end of beta period."""
    subject = "Thank you for beta testing Aganim!"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">Thank you, {merchant_name}!</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  The closed beta period is wrapping up, and we want to sincerely thank you
  for being part of it. Your usage and feedback have been invaluable in shaping
  Aganim into a better product.
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>What happens next:</strong>
</p>
<ul style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>Your access continues — nothing changes right now</li>
  <li>When we launch publicly, beta testers get the first month free</li>
  <li>If you'd like to share a testimonial, simply reply to this email</li>
</ul>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Thank you for helping us build something great. We couldn't have done it
  without merchants like you.
</p>
{_cta_button("Open Aganim", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"Thank you, {merchant_name}!\n\n"
        f"The closed beta is wrapping up. Your feedback has been invaluable.\n\n"
        f"What's next:\n"
        f"- Your access continues\n"
        f"- Beta testers get first month free at launch\n"
        f"- Reply to share a testimonial\n\n"
        f"Open Aganim: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body
