"""
Unit tests for the SES email service.

Covers:
- Lazy SES client initialisation
- send_email: success, SES error propagation
- send_bulk_email: partial failure handling, all-success, all-fail
- Environment variable defaults
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock  # noqa: F401


# ---------------------------------------------------------------------------
# Reset the module-level SES client between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_ses_client():
    import src.ecommerce.services.email_service as mod
    mod._ses_client = None
    yield
    mod._ses_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ses_client(message_id="test-msg-id-001"):
    """Return a mock SES client that succeeds on send_email."""
    client = MagicMock()
    client.send_email.return_value = {"MessageId": message_id}
    return client


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

class TestClientInit:
    @patch.dict("os.environ", {
        "AWS_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "AKID",
        "AWS_SECRET_ACCESS_KEY": "SECRET",
    })
    @patch("boto3.client")
    def test_lazy_client_created_on_first_call(self, mock_boto_client):
        from src.ecommerce.services.email_service import _get_ses_client

        mock_boto_client.return_value = MagicMock()
        client = _get_ses_client()

        mock_boto_client.assert_called_once_with(
            "ses",
            region_name="eu-west-1",
            aws_access_key_id="AKID",
            aws_secret_access_key="SECRET",
        )
        assert client is not None

    @patch.dict("os.environ", {
        "AWS_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "AKID",
        "AWS_SECRET_ACCESS_KEY": "SECRET",
    })
    @patch("boto3.client")
    def test_client_reused_on_second_call(self, mock_boto_client):
        from src.ecommerce.services.email_service import _get_ses_client

        mock_boto_client.return_value = MagicMock()
        c1 = _get_ses_client()
        c2 = _get_ses_client()

        mock_boto_client.assert_called_once()
        assert c1 is c2

    @patch.dict("os.environ", {}, clear=True)
    @patch("boto3.client")
    def test_default_region_when_env_missing(self, mock_boto_client):
        from src.ecommerce.services.email_service import _get_ses_client

        mock_boto_client.return_value = MagicMock()
        _get_ses_client()

        call_kwargs = mock_boto_client.call_args
        assert call_kwargs[1]["region_name"] == "us-east-1"


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------

class TestSendEmail:
    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_send_email_success(self, mock_get_client):
        from src.ecommerce.services.email_service import send_email

        ses = _mock_ses_client("msg-123")
        mock_get_client.return_value = ses

        result = await send_email(
            to="merchant@example.com",
            subject="Hello",
            html_body="<h1>Hi</h1>",
            text_body="Hi",
        )

        assert result["message_id"] == "msg-123"
        ses.send_email.assert_called_once()
        call_kwargs = ses.send_email.call_args[1]
        assert call_kwargs["Destination"]["ToAddresses"] == ["merchant@example.com"]
        assert call_kwargs["Message"]["Subject"]["Data"] == "Hello"
        assert call_kwargs["Message"]["Body"]["Html"]["Data"] == "<h1>Hi</h1>"
        assert call_kwargs["Message"]["Body"]["Text"]["Data"] == "Hi"

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_send_email_with_reply_to(self, mock_get_client):
        from src.ecommerce.services.email_service import send_email

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        await send_email(
            to="merchant@example.com",
            subject="Re: inquiry",
            html_body="<p>reply</p>",
            text_body="reply",
            reply_to="support@crossborderagent.com",
        )

        call_kwargs = ses.send_email.call_args[1]
        assert call_kwargs["ReplyToAddresses"] == ["support@crossborderagent.com"]

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_send_email_no_reply_to_omits_key(self, mock_get_client):
        from src.ecommerce.services.email_service import send_email

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        await send_email(
            to="x@y.com", subject="s", html_body="<b>h</b>", text_body="t"
        )

        call_kwargs = ses.send_email.call_args[1]
        assert "ReplyToAddresses" not in call_kwargs

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_send_email_ses_error_propagates(self, mock_get_client):
        from src.ecommerce.services.email_service import send_email

        ses = MagicMock()
        ses.send_email.side_effect = Exception("SES MessageRejected")
        mock_get_client.return_value = ses

        with pytest.raises(Exception, match="SES MessageRejected"):
            await send_email(
                to="bad@example.com",
                subject="Test",
                html_body="<p>x</p>",
                text_body="x",
            )

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_send_email_uses_custom_from_address(self, mock_get_client):
        from src.ecommerce.services.email_service import send_email
        import os

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        old = os.environ.get("SES_FROM_ADDRESS")
        os.environ["SES_FROM_ADDRESS"] = "custom@brand.com"
        try:
            await send_email(to="x@y.com", subject="s", html_body="h", text_body="t")
        finally:
            if old is None:
                os.environ.pop("SES_FROM_ADDRESS", None)
            else:
                os.environ["SES_FROM_ADDRESS"] = old

        call_kwargs = ses.send_email.call_args[1]
        assert call_kwargs["Source"] == "custom@brand.com"


# ---------------------------------------------------------------------------
# send_bulk_email
# ---------------------------------------------------------------------------

class TestSendBulkEmail:
    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_all_succeed(self, mock_get_client):
        from src.ecommerce.services.email_service import send_bulk_email

        ses = _mock_ses_client("bulk-ok")
        mock_get_client.return_value = ses

        results = await send_bulk_email(
            recipients=["a@b.com", "c@d.com"],
            subject="Promo",
            html_body="<p>promo</p>",
            text_body="promo",
        )

        assert len(results) == 2
        assert all(r["status"] == "sent" for r in results)
        assert all(r["message_id"] == "bulk-ok" for r in results)
        assert ses.send_email.call_count == 2

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_partial_failure(self, mock_get_client):
        from src.ecommerce.services.email_service import send_bulk_email

        ses = MagicMock()
        ses.send_email.side_effect = [
            {"MessageId": "ok-1"},
            Exception("Bounce"),
            {"MessageId": "ok-3"},
        ]
        mock_get_client.return_value = ses

        results = await send_bulk_email(
            recipients=["a@b.com", "bad@bounce.com", "c@d.com"],
            subject="Test",
            html_body="h",
            text_body="t",
        )

        assert len(results) == 3
        assert results[0]["status"] == "sent"
        assert results[1]["status"] == "failed"
        assert "Bounce" in results[1]["error"]
        assert results[2]["status"] == "sent"

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_all_fail(self, mock_get_client):
        from src.ecommerce.services.email_service import send_bulk_email

        ses = MagicMock()
        ses.send_email.side_effect = Exception("Throttled")
        mock_get_client.return_value = ses

        results = await send_bulk_email(
            recipients=["a@b.com", "c@d.com"],
            subject="s",
            html_body="h",
            text_body="t",
        )

        assert len(results) == 2
        assert all(r["status"] == "failed" for r in results)

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_empty_recipients_returns_empty(self, mock_get_client):
        from src.ecommerce.services.email_service import send_bulk_email

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        results = await send_bulk_email(
            recipients=[],
            subject="s",
            html_body="h",
            text_body="t",
        )

        assert results == []
        ses.send_email.assert_not_called()


# ---------------------------------------------------------------------------
# send_rate_limited_bulk_email
# ---------------------------------------------------------------------------

class TestSendRateLimitedBulkEmail:
    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_all_succeed_with_delay(self, mock_get_client, mock_sleep):
        from src.ecommerce.services.email_service import send_rate_limited_bulk_email

        ses = _mock_ses_client("rl-ok")
        mock_get_client.return_value = ses

        results = await send_rate_limited_bulk_email(
            recipients=["a@b.com", "c@d.com", "e@f.com"],
            subject="Rate Limited",
            html_body="<p>hi</p>",
            text_body="hi",
            delay_seconds=0.01,
        )

        assert len(results) == 3
        assert all(r["status"] == "sent" for r in results)
        assert mock_sleep.call_count == 2  # sleep between each, not after last

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_partial_failure_continues(self, mock_get_client, mock_sleep):
        from src.ecommerce.services.email_service import send_rate_limited_bulk_email

        ses = MagicMock()
        ses.send_email.side_effect = [
            {"MessageId": "ok-1"},
            Exception("Bounce"),
            {"MessageId": "ok-3"},
        ]
        mock_get_client.return_value = ses

        results = await send_rate_limited_bulk_email(
            recipients=["a@b.com", "bad@bounce.com", "c@d.com"],
            subject="Test",
            html_body="h",
            text_body="t",
            delay_seconds=0.01,
        )

        assert results[0]["status"] == "sent"
        assert results[1]["status"] == "failed"
        assert results[2]["status"] == "sent"

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_single_recipient_no_sleep(self, mock_get_client, mock_sleep):
        from src.ecommerce.services.email_service import send_rate_limited_bulk_email

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        results = await send_rate_limited_bulk_email(
            recipients=["only@one.com"],
            subject="s",
            html_body="h",
            text_body="t",
        )

        assert len(results) == 1
        assert results[0]["status"] == "sent"
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.ecommerce.services.email_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    async def test_empty_recipients(self, mock_get_client, mock_sleep):
        from src.ecommerce.services.email_service import send_rate_limited_bulk_email

        ses = _mock_ses_client()
        mock_get_client.return_value = ses

        results = await send_rate_limited_bulk_email(
            recipients=[], subject="s", html_body="h", text_body="t",
        )

        assert results == []
        mock_sleep.assert_not_called()
