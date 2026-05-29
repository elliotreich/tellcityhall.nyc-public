"""Tests for email sender (unit tests — no actual SMTP)."""
import pytest

from engine.email_sender import EmailSender, EmailDeliveryResult, get_email_sender


class TestEmailDeliveryResult:
    def test_success_result(self):
        result = EmailDeliveryResult(success=True, message="Sent OK")
        assert result.success
        assert result.message == "Sent OK"
        assert result.error == ""

    def test_failure_result(self):
        result = EmailDeliveryResult(success=False, error="Connection refused")
        assert not result.success
        assert result.error == "Connection refused"

    def test_default_values(self):
        result = EmailDeliveryResult(success=False)
        assert not result.success
        assert result.message == ""
        assert result.error == ""


class TestGetEmailSender:
    def test_returns_singleton(self):
        s1 = get_email_sender()
        s2 = get_email_sender()
        assert s1 is s2


class TestBuildBody:
    def test_includes_constituent_info(self):
        sender = EmailSender()
        body = sender._build_body(
            official_title="Council Member",
            official_name="Jane Doe",
            first_name="John",
            last_name="Smith",
            address_street="350 Jay St",
            address_city="Brooklyn",
            address_state="NY",
            address_zip="11201",
            email="john@example.com",
            topic="Transportation",
            message="I support bike lanes.",
        )
        assert "John Smith" in body
        assert "350 Jay St" in body
        assert "Brooklyn, NY 11201" in body
        assert "john@example.com" in body
        assert "Transportation" in body
        assert "I support bike lanes." in body

    def test_plain_text_no_html(self):
        sender = EmailSender()
        body = sender._build_body(
            official_title="Test Official",
            official_name="Test Name",
            first_name="User",
            last_name="Person",
            address_street="1 Test St",
            address_city="Testville",
            address_state="NY",
            address_zip="10000",
            email="user@test.com",
            topic="Test Topic",
            message="Test message content.",
        )
        assert "<html>" not in body.lower()
        assert "<body>" not in body.lower()
        assert "Test message content." in body

    def test_includes_email_for_reply(self):
        sender = EmailSender()
        body = sender._build_body(
            official_title="Test Official",
            official_name="Test Name",
            first_name="User",
            last_name="Person",
            address_street="1 Test St",
            address_city="Testville",
            address_state="NY",
            address_zip="10000",
            email="user@test.com",
            topic="Test Topic",
            message="Test message content.",
        )
        assert "user@test.com" in body

    def test_official_title_in_greeting(self):
        sender = EmailSender()
        body = sender._build_body(
            official_title="State Senator",
            official_name="Bob Jones",
            first_name="Alice",
            last_name="Brown",
            address_street="1 Main St",
            address_city="New York",
            address_state="NY",
            address_zip="10001",
            email="alice@example.com",
            topic="Housing",
            message="More affordable housing please.",
        )
        assert "Dear State Senator Bob Jones" in body
        assert "Alice Brown" in body
        assert "Housing" in body


class TestComposeEmail:
    def test_plain_text_mime(self):
        sender = EmailSender()
        msg = sender._compose_email(
            to_email="official@gov.nyc",
            to_name="Test Official",
            subject="Message from a constituent",
            body_text="Dear Official,\n\nTest message.",
            reply_to="constituent@example.com",
        )
        assert msg.get_content_type() == "text/plain"
        assert msg["To"] == "official@gov.nyc"
        assert msg["Subject"] == "Message from a constituent"
        assert msg["Reply-To"] == "constituent@example.com"
        assert msg["From"] is not None

    def test_utf8_encoding(self):
        sender = EmailSender()
        msg = sender._compose_email(
            to_email="official@gov.nyc",
            to_name="Test Official",
            subject="Constituent message",
            body_text="Dear Official,\n\nI have concerns about the city's budget.",
            reply_to="jane@example.com",
        )
        assert msg.get_content_charset() in (None, "utf-8") or "utf-8" in str(msg.get_content_charset()).lower()
