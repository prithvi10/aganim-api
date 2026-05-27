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

_UI_BASE_URL = os.getenv("PUBLIC_SITE_URL", "https://aganim-ai.com")
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


def _showcase_layout(content_html: str) -> str:
    """
    Wider responsive wrapper for the showcase email.

    Uses max-width:800px on desktop and collapses to 100% on mobile,
    giving screenshots room to breathe on larger screens.
    """
    return f"""\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
  @media only screen and (max-width: 640px) {{
    .showcase-container {{ width: 100% !important; padding: 16px !important; }}
    .showcase-body {{ padding: 24px 16px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:32px 0;">
<tr><td align="center">
<table role="presentation" class="showcase-container" cellpadding="0" cellspacing="0" style="width:100%;max-width:800px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

<!-- Header -->
<tr><td style="background-color:{_BRAND_COLOR};padding:28px 40px;text-align:center;">
  <img src="{_LOGO_URL}" alt="Aganim" width="48" height="48" style="display:inline-block;vertical-align:middle;border-radius:8px;">
  <span style="color:#ffffff;font-size:22px;font-weight:700;margin-left:12px;vertical-align:middle;">Aganim</span>
</td></tr>

<!-- Body -->
<tr><td class="showcase-body" style="padding:36px 48px;">
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
    "beta_showcase": lambda name, **kw: beta_showcase_email(name, **kw),
    "beta_exit": lambda name, **kw: beta_exit_email(name),
}


# ── Beta Templates ────────────────────────────────────────────────

_INSTALL_URL = "https://admin.shopify.com/oauth/install?client_id=315cfaf63c9baf27e4ba9a22b91b168e"


def beta_invite_email(merchant_name: str, signup_url: str = "") -> tuple[str, str, str]:
    """Cold outreach to invite a merchant into the closed beta."""
    subject = "【特別ご招待】Aganim AI — 全Pro機能を6週間無料でお試しください"

    cta_url = signup_url or _INSTALL_URL
    cta_label = "無料で始める" if signup_url else "今すぐ試す"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">{merchant_name} 様</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  限定のマーチャント様に、<strong>Aganim AI</strong>の全機能を
  <strong>6週間完全無料</strong>でご体験いただける特別プログラムへご招待いたします。
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Aganim AIは、あなたのショップを次のレベルへ引き上げるAIツールです：
</p>
<ul style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>商品ページを海外市場向けに高品質なコピーへAIリライト</li>
  <li>SEO最適化で検索順位アップ</li>
  <li>プロ品質のマーケティング画像を自動生成</li>
  <li>多言語対応でグローバル展開をサポート</li>
</ul>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>Pro機能すべてが無料</strong> — クレジットカード不要、いつでも解約可能です。
  セットアップは5分で完了します。
</p>
{_cta_button(cta_label, cta_url)}
<p style="margin:8px 0 0;font-size:14px;color:#6b7280;">
  ご質問がございましたら、このメールにご返信ください。お待ちしております！
</p>"""

    html_body = _base_layout(content)
    text_body = (
        f"{merchant_name} 様\n\n"
        f"限定マーチャント様向けに、Aganim AIの全Pro機能を6週間無料でご体験いただける\n"
        f"特別プログラムへご招待いたします。\n\n"
        f"・商品ページのAIリライト\n"
        f"・SEO最適化\n"
        f"・マーケティング画像の自動生成\n"
        f"・多言語対応\n\n"
        f"無料で始める: {cta_url}\n\n"
        f"ご質問がございましたら、このメールにご返信ください。\n"
    )
    return subject, html_body, text_body


def beta_welcome_email(merchant_name: str) -> tuple[str, str, str]:
    """Welcome email sent when a beta merchant installs the app."""
    subject = "Aganim AI へようこそ！全Pro機能がご利用可能です"

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">{merchant_name} 様、ようこそ！</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Aganimの全Pro機能に<strong>無制限アクセス</strong>が有効になりました。
  これからあなたのショップをグローバルに成長させるお手伝いをいたします。
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>ご利用いただける機能：</strong>
</p>
<ul style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>商品ページのAIリライト（無制限）</li>
  <li>SEO最適化とキーワード分析</li>
  <li>マーケティングコピーの自動生成</li>
  <li>プロ品質の商品画像生成</li>
</ul>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>おすすめの始め方：</strong>
</p>
<ol style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>Shopify管理画面からAganimを開く</li>
  <li>ブランドソウルウィザードを完了する（2分）</li>
  <li>売れ筋商品でリライトを試す</li>
</ol>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  何かお困りのことがございましたら、いつでもこのメールにご返信ください。
  全力でサポートいたします。
</p>
{_cta_button("Aganimを開く", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"{merchant_name} 様、ようこそ！\n\n"
        f"Aganimの全Pro機能に無制限アクセスが有効になりました。\n\n"
        f"おすすめの始め方:\n"
        f"1. Shopify管理画面からAganimを開く\n"
        f"2. ブランドソウルウィザードを完了する\n"
        f"3. 売れ筋商品でリライトを試す\n\n"
        f"Aganimを開く: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body


def beta_checkin_email(merchant_name: str, feedback_url: str = "") -> tuple[str, str, str]:
    """Weekly check-in nudge for beta merchants."""
    subject = "Aganimのご利用状況はいかがですか？"

    feedback_cta = ""
    if feedback_url:
        feedback_cta = f"""
<p style="margin:24px 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  ご体験をお聞かせください：
</p>
{_cta_button("ご感想をお聞かせください", feedback_url)}"""

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">{merchant_name} 様</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  ベータ版のご利用状況を確認させていただいています。
  AIリライター機能で商品ページをお試しいただけましたか？
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>ワンポイント：</strong>売れ筋商品でSEOオプティマイザーをお試しください。
  ターゲット市場のGoogle検索データを分析し、オーガニックトラフィックを増やす
  タイトル・メタ改善を提案します。
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  不具合や改善のアイデアがございましたら、このメールにご返信ください。
  いただいたフィードバックは今後の開発に反映いたします。
</p>
{feedback_cta}
{_cta_button("Aganimを開く", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"{merchant_name} 様\n\n"
        f"ベータ版のご利用状況を確認させていただいています。\n\n"
        f"ワンポイント: 売れ筋商品でSEOオプティマイザーをお試しください。\n\n"
        f"フィードバックやご質問がございましたら、このメールにご返信ください。\n"
        + (f"フィードバックフォーム: {feedback_url}\n" if feedback_url else "")
        + f"Aganimを開く: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body


def beta_feedback_request_email(merchant_name: str, feedback_url: str = "") -> tuple[str, str, str]:
    """Structured feedback request for beta merchants."""
    subject = "Aganimについてのフィードバック（2分で完了）"

    feedback_cta = ""
    if feedback_url:
        feedback_cta = _cta_button("フィードバックフォームに回答する", feedback_url)

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">{merchant_name} 様</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  Aganimをご利用いただきありがとうございます。ぜひご感想をお聞かせください。
  いただいたフィードバックは今後のロードマップに直接反映いたします。
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>3つの簡単な質問：</strong>
</p>
<ol style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>最も価値を感じた機能は何ですか？</li>
  <li>最も不満に感じた点は何ですか？</li>
  <li>ベータ終了後、このツールに料金をお支払いいただけますか？</li>
</ol>
{feedback_cta}
<p style="margin:12px 0;font-size:14px;color:#6b7280;line-height:1.6;">
  フォームが開けない場合は、このメールにご返信いただくだけでも構いません。
</p>
{_cta_button("サポートページ", _SUPPORT_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"{merchant_name} 様\n\n"
        f"Aganimについてのフィードバックをお聞かせください（2分で完了）。\n\n"
        f"3つの簡単な質問:\n"
        f"1. 最も価値を感じた機能は何ですか？\n"
        f"2. 最も不満に感じた点は何ですか？\n"
        f"3. ベータ終了後、このツールに料金をお支払いいただけますか？\n\n"
        + (f"フィードバックフォーム: {feedback_url}\n\n" if feedback_url else "")
        + f"このメールにご返信ください。\n"
        f"サポート: {_SUPPORT_URL}\n"
    )
    return subject, html_body, text_body


_R2_BASE_URL = "https://pub-2d05fd38ba8549c0811a1e0bc9426e81.r2.dev"
_BETA_OUTREACH_PATH = "beta_outreach"
_SENDER_EMAIL = "prithviraj@aganim-ai.com"
_LINKEDIN_URL = "https://www.linkedin.com/in/prithviraj-pawar-69058ab5/"
_BETA_ENROLLMENT_URL = "https://aganim-ai.com/beta"


def beta_showcase_email(
    merchant_name: str,
    store_key: str = "",
    brand_name: str = "",
    image_filenames: list[str] | None = None,
    image_urls: list[str] | None = None,
    signup_url: str = "",
) -> tuple[str, str, str]:
    """
    Japanese outreach email with before/after transformation showcase.

    Image carousel picks up files from R2:
        {R2_BASE_URL}/beta_outreach/{store_key}/{filename}

    Filenames are used as carousel captions (extension stripped, underscores
    replaced with spaces).

    Parameters:
        merchant_name: Formal name (e.g. "むす美（山田繊維株式会社）")
        store_key: Folder name in R2 (e.g. "musubi" from test-aganim-musubi)
        brand_name: Display brand name (e.g. "MUSUBI Furoshiki")
        image_filenames: List of filenames in the R2 folder (e.g. ["1. Rewrite in 12+ languages.png"])
        image_urls: Override with explicit full URLs if not using R2 convention
        signup_url: Custom CTA link (defaults to beta enrollment form)
    """
    subject = "【特別ご招待】あなたの商品を12以上の海外市場向けに変革 — 6週間無料Pro体験"

    cta_url = signup_url or _BETA_ENROLLMENT_URL
    display_brand = brand_name or merchant_name

    # Build image URLs and captions from R2 bucket or use explicit URLs
    from urllib.parse import quote as _url_quote

    images: list[tuple[str, str]] = []  # (url, caption)
    if image_urls:
        images = [(url, "") for url in image_urls]
    elif image_filenames and store_key:
        for fname in image_filenames:
            encoded_fname = _url_quote(fname, safe="")
            url = f"{_R2_BASE_URL}/{_BETA_OUTREACH_PATH}/{store_key}/{encoded_fname}"
            caption = fname.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
            images.append((url, caption))

    # Build image grid — first image full-width, rest in 2-column table
    # Each image links to its full-size version for zooming into text details
    carousel_html = ""
    if images:
        # First image — hero, full width
        hero_url, hero_caption = images[0]
        hero_caption_html = ""
        if hero_caption:
            hero_caption_html = (
                f'<p style="margin:8px 0 0;font-size:13px;color:#374151;'
                f'font-weight:600;text-align:center;">{hero_caption}</p>'
            )
        hero_html = (
            f'<a href="{hero_url}" target="_blank" style="text-decoration:none;">'
            f'<div style="border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">'
            f'<img src="{hero_url}" alt="{hero_caption or "最適化サンプル 1"}" '
            f'style="width:100%;height:auto;display:block;" />'
            f'</div>'
            f'</a>'
            f'{hero_caption_html}'
        )

        # Remaining images — 2-column grid
        grid_html = ""
        remaining = images[1:]
        if remaining:
            rows_html = ""
            for i in range(0, len(remaining), 2):
                cells = ""
                for j in range(2):
                    idx = i + j
                    if idx < len(remaining):
                        img_url, caption = remaining[idx]
                        caption_html = ""
                        if caption:
                            caption_html = (
                                f'<p style="margin:8px 0 0;font-size:12px;color:#374151;'
                                f'font-weight:600;text-align:center;">{caption}</p>'
                            )
                        cells += (
                            f'<td style="width:50%;padding:8px;vertical-align:top;">'
                            f'<a href="{img_url}" target="_blank" style="text-decoration:none;">'
                            f'<div style="border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">'
                            f'<img src="{img_url}" alt="{caption or f"最適化サンプル {idx+2}"}" '
                            f'style="width:100%;height:auto;display:block;" />'
                            f'</div>'
                            f'</a>'
                            f'{caption_html}'
                            f'</td>'
                        )
                    else:
                        cells += '<td style="width:50%;padding:8px;"></td>'
                rows_html += f'<tr>{cells}</tr>'
            grid_html = (
                f'<table role="presentation" cellpadding="0" cellspacing="0" '
                f'width="100%" style="margin-top:16px;">'
                f'{rows_html}</table>'
            )

        carousel_html = f"""\
<div style="margin:24px 0;">
{hero_html}
{grid_html}
  <p style="margin:12px 0 0;font-size:11px;color:#9ca3af;text-align:center;">
    画像をクリックすると拡大表示されます（{len(images)}枚）
  </p>
</div>"""

    content = f"""\
<h1 style="margin:0 0 8px;font-size:24px;color:#111827;">
  {merchant_name} 様
</h1>
<p style="margin:0 0 20px;font-size:14px;color:#6b7280;">
  {display_brand} の商品で実際にAganim AIを使用した最適化結果をご覧ください
</p>

<div style="background:linear-gradient(135deg,#EEF2FF,#E0E7FF);border-radius:12px;padding:20px 24px;margin:0 0 24px;">
  <h2 style="margin:0 0 8px;font-size:18px;color:#1E40AF;">
    あなたの商品ページを海外市場向けに変革します
  </h2>
  <p style="margin:0;font-size:14px;color:#374151;line-height:1.6;">
    Aganim AIを使って<strong>{display_brand}</strong>の商品を海外のお客様向けに
    最適化しました。わずか数分でこれだけの成果が得られます：
  </p>
</div>

<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 20px;">
<tr>
<td style="width:33%;text-align:center;padding:12px 8px;background:#f9fafb;border-radius:8px 0 0 8px;">
  <div style="font-size:24px;font-weight:700;color:{_BRAND_COLOR};">12+</div>
  <div style="font-size:11px;color:#6b7280;margin-top:4px;">対応市場</div>
</td>
<td style="width:34%;text-align:center;padding:12px 8px;background:#f9fafb;">
  <div style="font-size:24px;font-weight:700;color:{_BRAND_COLOR};">AI</div>
  <div style="font-size:11px;color:#6b7280;margin-top:4px;">ブランド対応コピー</div>
</td>
<td style="width:33%;text-align:center;padding:12px 8px;background:#f9fafb;border-radius:0 8px 8px 0;">
  <div style="font-size:24px;font-weight:700;color:{_BRAND_COLOR};">5分</div>
  <div style="font-size:11px;color:#6b7280;margin-top:4px;">1商品あたり</div>
</td>
</tr>
</table>

{carousel_html}

<h3 style="margin:24px 0 12px;font-size:16px;color:#111827;">Aganim AIが{display_brand}に提供した最適化：</h3>
<ul style="padding-left:20px;margin:0 0 20px;color:#374151;line-height:1.8;">
  <li><strong>ブランドソウル分析</strong> — ブランドのアイデンティティ、トーン、価値観を深く理解</li>
  <li><strong>商品コピーリライト</strong> — 文化に配慮した英語の商品説明文＋SEOキーワード最適化</li>
  <li><strong>画像エンハンスメント</strong> — プロ品質の商品写真、背景のクリーンアップ</li>
  <li><strong>価格インテリジェンス</strong> — ターゲット市場の競合価格分析</li>
  <li><strong>SNS対応</strong> — Instagram/Facebook広告クリエイティブの自動生成</li>
</ul>

<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;padding:16px 20px;margin:0 0 16px;">
  <p style="margin:0;font-size:14px;color:#92400E;line-height:1.6;">
    <strong>特別先行オファー：</strong>通常月額$49のPro全機能を
    <strong>6週間完全無料</strong>でご利用いただけます。クレジットカード不要、
    いつでも解約可能。グローバル展開を目指す日本のマーチャント様限定のご招待です。
  </p>
</div>

<div style="background:#F9FAFB;border-left:4px solid {_BRAND_COLOR};border-radius:4px;padding:16px 20px;margin:0 0 24px;">
  <p style="margin:0;font-size:14px;color:#374151;line-height:1.6;">
    <strong>【パートナーシップ特典】</strong><br>
    6週間のプログラム期間終了後、素晴らしい成果を上げられたブランド様を、当社の公式ウェブサイトや海外向け発信にて「注目の成功事例」としてご紹介させていただく枠をご用意しております。{display_brand}のさらなる認知度向上にぜひお役立てください。
  </p>
</div>

<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:24px 0;">
<tr>
<td style="width:48%;text-align:center;">
  <table role="presentation" cellpadding="0" cellspacing="0" style="display:inline-block;">
  <tr><td style="background-color:#ffffff;border:2px solid {_BRAND_COLOR};border-radius:8px;padding:14px 24px;">
    <a href="https://aganim-ai.com" style="color:{_BRAND_COLOR};font-size:14px;font-weight:600;text-decoration:none;display:inline-block;">Aganim AI を見る</a>
  </td></tr></table>
</td>
<td style="width:4%;"></td>
<td style="width:48%;text-align:center;">
  <table role="presentation" cellpadding="0" cellspacing="0" style="display:inline-block;">
  <tr><td style="background-color:{_BRAND_COLOR};border-radius:8px;padding:14px 24px;">
    <a href="{cta_url}" style="color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;display:inline-block;">Pro特典を受け取る</a>
  </td></tr></table>
</td>
</tr>
</table>

<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 0;width:100%;border-top:1px solid #e5e7eb;padding-top:20px;">
<tr>
<td style="padding:8px 0;">
  <a href="https://aganim-ai.com" style="color:{_BRAND_COLOR};text-decoration:underline;font-size:13px;">Aganim AI ウェブサイト</a>
  &nbsp;&middot;&nbsp;
  <a href="https://apps.shopify.com/aganim" style="color:{_BRAND_COLOR};text-decoration:underline;font-size:13px;">Shopify App Store</a>
  &nbsp;&middot;&nbsp;
  <a href="{_SUPPORT_URL}" style="color:{_BRAND_COLOR};text-decoration:underline;font-size:13px;">サポート</a>
</td>
</tr>
</table>

<p style="margin:16px 0 0;font-size:13px;color:#6b7280;line-height:1.5;">
  これは{display_brand}様への個別ご招待です。実際の商品データでAganim AIを実行し、
  デモではない本物の結果をお見せしています。ご興味がございましたら、このメールに
  ご返信ください。
</p>

<table role="presentation" cellpadding="0" cellspacing="0" style="margin:16px 0 0;">
<tr>
<td style="padding:0;">
  <p style="margin:0;font-size:13px;color:#374151;line-height:1.5;">
    Prithviraj Pawar<br>
    <span style="color:#6b7280;">Founder & CEO, Aganim AI</span><br>
    <a href="mailto:{_SENDER_EMAIL}" style="color:{_BRAND_COLOR};text-decoration:none;font-size:12px;">{_SENDER_EMAIL}</a>
    &nbsp;&middot;&nbsp;
    <a href="{_LINKEDIN_URL}" style="color:{_BRAND_COLOR};text-decoration:none;font-size:12px;">LinkedIn</a>
  </p>
</td>
</tr>
</table>"""

    html_body = _showcase_layout(content)

    text_body = (
        f"{merchant_name} 様\n\n"
        f"Aganim AIを使って{display_brand}の商品を海外市場向けに最適化しました。\n\n"
        f"実現した最適化：\n"
        f"・ブランドソウル分析 — アイデンティティとトーンを深く理解\n"
        f"・商品コピーリライト — 文化に配慮した英語＋SEO最適化\n"
        f"・画像エンハンスメント — プロ品質の商品写真\n"
        f"・価格インテリジェンス — 競合市場分析\n"
        f"・SNS対応 — 広告クリエイティブ自動生成\n\n"
        f"【特別先行オファー】Pro全機能を6週間無料でご利用いただけます。\n"
        f"クレジットカード不要。\n\n"
        f"【パートナーシップ特典】\n"
        f"6週間のプログラム期間終了後、素晴らしい成果を上げられたブランド様を、"
        f"当社の公式ウェブサイトや海外向け発信にて「注目の成功事例」として"
        f"ご紹介させていただく枠をご用意しております。"
        f"{display_brand}のさらなる認知度向上にぜひお役立てください。\n\n"
        f"今すぐ参加: {cta_url}\n\n"
        f"Aganim AI を見る: https://aganim-ai.com\n"
        f"Shopify App Store: https://apps.shopify.com/aganim\n"
        f"サポート: {_SUPPORT_URL}\n\n"
        f"---\n"
        f"Prithviraj Pawar\n"
        f"Founder & CEO, Aganim AI\n"
        f"{_SENDER_EMAIL}\n"
        f"LinkedIn: {_LINKEDIN_URL}\n"
    )

    return subject, html_body, text_body


def beta_exit_email(merchant_name: str, feedback_url: str = "") -> tuple[str, str, str]:
    """Thank you / exit email at end of beta period."""
    subject = "Aganim ベータテストへのご参加、ありがとうございました！"

    feedback_cta = ""
    if feedback_url:
        feedback_cta = f"""
<p style="margin:24px 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  最後にご体験をお聞かせください：
</p>
{_cta_button("ご感想をお聞かせください", feedback_url)}"""

    content = f"""\
<h1 style="margin:0 0 16px;font-size:24px;color:#111827;">{merchant_name} 様、ありがとうございます！</h1>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  クローズドベータ期間が終了に近づいています。ご参加いただき、
  心より感謝申し上げます。いただいたご利用データとフィードバックは、
  Aganimをより良い製品に仕上げるために大変貴重なものでした。
</p>
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  <strong>今後について：</strong>
</p>
<ul style="padding-left:20px;margin:12px 0;color:#374151;line-height:1.8;">
  <li>現在のアクセスはそのまま継続されます</li>
  <li>正式リリース時、ベータテスターは初月無料でご利用いただけます</li>
  <li>推薦コメントをいただける場合は、このメールにご返信ください</li>
</ul>
{feedback_cta}
<p style="margin:0 0 12px;font-size:16px;color:#374151;line-height:1.6;">
  素晴らしい製品を作るお手伝いをいただき、ありがとうございました。
  マーチャントの皆様のご協力なしには実現できませんでした。
</p>
{_cta_button("Aganimを開く", _LANDING_URL)}"""

    html_body = _base_layout(content)
    text_body = (
        f"{merchant_name} 様、ありがとうございます！\n\n"
        f"クローズドベータ期間が終了に近づいています。フィードバックは大変貴重でした。\n\n"
        f"今後について:\n"
        f"- 現在のアクセスはそのまま継続されます\n"
        f"- 正式リリース時、ベータテスターは初月無料\n"
        f"- 推薦コメントはこのメールにご返信ください\n\n"
        + (f"フィードバックフォーム: {feedback_url}\n\n" if feedback_url else "")
        + f"Aganimを開く: {_LANDING_URL}\n"
    )
    return subject, html_body, text_body
