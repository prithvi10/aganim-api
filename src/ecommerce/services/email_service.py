"""
SES Email Service — sends transactional emails via Amazon SES.

Required env vars:
    AWS_REGION           -- SES region (e.g. us-east-1)
    AWS_ACCESS_KEY_ID    -- IAM credentials (already set for R2)
    AWS_SECRET_ACCESS_KEY
    SES_FROM_ADDRESS     -- Verified SES sender (e.g. Aganim <architect@aganim-ai.com>)
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

_ses_client = None

BATCH_DELAY_SECONDS = 1.0


def _get_ses_client():
    """Lazily create a boto3 SES client."""
    global _ses_client
    if _ses_client is None:
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for SES email. Install it with: pip install boto3"
            )

        _ses_client = boto3.client(
            "ses",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    return _ses_client


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    reply_to: Optional[str] = None,
) -> dict:
    """
    Send a single email via SES.

    Returns dict with ``message_id`` on success, raises on failure.
    """
    from_address = os.getenv(
        "SES_FROM_ADDRESS", '"Aganim" <architect@aganim-ai.com>'
    )
    client = _get_ses_client()

    message: dict = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {
            "Html": {"Data": html_body, "Charset": "UTF-8"},
            "Text": {"Data": text_body, "Charset": "UTF-8"},
        },
    }

    kwargs: dict = {
        "Source": from_address,
        "Destination": {"ToAddresses": [to]},
        "Message": message,
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(None, lambda: client.send_email(**kwargs))

    message_id = response.get("MessageId", "")
    logger.info("[SES] sent to=%s subject=%r message_id=%s", to, subject, message_id)
    return {"message_id": message_id}


async def send_bulk_email(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    reply_to: Optional[str] = None,
) -> list[dict]:
    """
    Send the same email to multiple recipients individually.

    Returns a list of result dicts, one per recipient.  Each dict contains
    ``email``, ``status`` (``"sent"`` / ``"failed"``), and ``message_id`` or
    ``error``.
    """
    results: list[dict] = []

    for email in recipients:
        try:
            resp = await send_email(
                to=email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                reply_to=reply_to,
            )
            results.append({"email": email, "status": "sent", **resp})
        except Exception as exc:
            logger.error("[SES] failed to=%s error=%s", email, exc)
            results.append({"email": email, "status": "failed", "error": str(exc)})

    return results


async def send_rate_limited_bulk_email(
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    reply_to: Optional[str] = None,
    delay_seconds: float = BATCH_DELAY_SECONDS,
) -> list[dict]:
    """
    Send to many recipients with a per-email delay to stay within SES rate
    limits (typically 14/s for new accounts).

    Sleeps ``delay_seconds`` (default 1s) between each send.  Failures for
    individual recipients are logged and collected, but sending continues.
    """
    results: list[dict] = []

    for idx, email in enumerate(recipients):
        try:
            resp = await send_email(
                to=email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                reply_to=reply_to,
            )
            results.append({"email": email, "status": "sent", **resp})
        except Exception as exc:
            logger.error("[SES] rate-limited send failed to=%s error=%s", email, exc)
            results.append({"email": email, "status": "failed", "error": str(exc)})

        if idx < len(recipients) - 1:
            await asyncio.sleep(delay_seconds)

    logger.info(
        "[SES] rate-limited bulk complete total=%d sent=%d failed=%d",
        len(results),
        sum(1 for r in results if r["status"] == "sent"),
        sum(1 for r in results if r["status"] == "failed"),
    )

    return results


async def send_threaded_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    reply_to: Optional[str] = None,
) -> dict:
    """
    Send an email with In-Reply-To/References headers for threading.
    Uses SES send_raw_email to inject custom headers.
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from_address = os.getenv(
        "SES_FROM_ADDRESS", '"Aganim" <architect@aganim-ai.com>'
    )
    client = _get_ses_client()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to

    if reply_to:
        msg["Reply-To"] = reply_to
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to}>"
    if references:
        msg["References"] = f"<{references}>"

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.send_raw_email(
            Source=from_address,
            Destinations=[to],
            RawMessage={"Data": msg.as_string()},
        ),
    )

    message_id = response.get("MessageId", "")
    logger.info("[SES] threaded send to=%s subject=%r message_id=%s in_reply_to=%s", to, subject, message_id, in_reply_to)
    return {"message_id": message_id}
