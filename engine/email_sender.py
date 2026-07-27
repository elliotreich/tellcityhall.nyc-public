"""
SMTP email sender for NYC Bridge.
Handles email composition and delivery to email-based officials.
"""
import asyncio
import time
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from config import (
    FROM_EMAIL,
    FROM_NAME,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_USE_TLS,
    SENDGRID_API_KEY,
    MAILGUN_API_KEY,
    MAILGUN_DOMAIN,
    EMAILS_PER_MINUTE,
    DIGEST_DOMAIN_DELAY,
)


@dataclass
class EmailDeliveryResult:
    """Result of an email delivery attempt."""
    success: bool
    message: str = ""
    smtp_response: str = ""
    error: str = ""


class EmailSender:
    """Async email sender with rate limiting."""

    def __init__(self):
        self._semaphore = asyncio.Semaphore(EMAILS_PER_MINUTE)
        self._last_send_time = 0.0
        self._domain_last_send: dict[str, float] = {}

    async def _rate_limit(self):
        """Enforce global rate limit to avoid spam filters."""
        async with self._semaphore:
            now = time.monotonic()
            min_interval = 60.0 / EMAILS_PER_MINUTE
            wait = self._last_send_time + min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_send_time = time.monotonic()

    @staticmethod
    def _extract_domain(email: str) -> str:
        """Return the lowercased domain portion of an email address."""
        idx = email.find("@")
        return email[idx + 1 :].strip().lower() if idx >= 0 else email.strip().lower()

    async def _domain_rate_limit(self, recipient_email: str):
        """Enforce per-domain rate limit to pace sends to the same mail server."""
        domain = self._extract_domain(recipient_email)
        now = time.monotonic()
        last = self._domain_last_send.get(domain, 0.0)
        wait = last + DIGEST_DOMAIN_DELAY - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._domain_last_send[domain] = time.monotonic()

    def _compose_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        reply_to: str,
    ) -> MIMEText:
        """Compose a plain-text email message."""
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Reply-To"] = reply_to
        msg["X-Mailer"] = "NYC Bridge (https://nyc-bridge.local)"
        return msg

    def _build_body(
        self,
        first_name: str,
        last_name: str,
        address_street: str,
        address_city: str,
        address_state: str,
        address_zip: str,
        email: str,
        topic: str,
        message: str,
        official_title: str,
        official_name: str,
    ) -> str:
        """Build a well-formatted constituent email body."""
        return (
            f"Dear {official_title} {official_name},\n\n"
            f"{first_name} {last_name}\n"
            f"{address_street}\n"
            f"{address_city}, {address_state} {address_zip}\n"
            f"{email}\n\n"
            f"Topic: {topic}\n\n"
            f"{message}\n"
        )

    async def send_email(
        self,
        to_email: str,
        official_title: str,
        official_name: str,
        first_name: str,
        last_name: str,
        address_street: str,
        address_city: str,
        address_state: str,
        address_zip: str,
        user_email: str,
        topic: str,
        message: str,
        subject_override: str = "",
    ) -> EmailDeliveryResult:
        """Send a constituent message to an official via email."""
        await self._rate_limit()

        subject = subject_override or f"Message from a constituent — {topic}"

        body = self._build_body(
            first_name=first_name,
            last_name=last_name,
            address_street=address_street,
            address_city=address_city,
            address_state=address_state,
            address_zip=address_zip,
            email=user_email,
            topic=topic,
            message=message,
            official_title=official_title,
            official_name=official_name,
        )

        # Prefer SendGrid API
        if SENDGRID_API_KEY:
            return await self._send_via_sendgrid(
                to_email, subject, body, user_email
            )

        # Then Mailgun
        if MAILGUN_API_KEY and MAILGUN_DOMAIN:
            return await self._send_via_mailgun(
                to_email, subject, body, user_email
            )

        # Fall back to direct SMTP
        return await self._send_via_smtp(
            to_email, official_name, subject, body, user_email
        )

    async def _send_via_smtp(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        reply_to: str,
    ) -> EmailDeliveryResult:
        """Send via direct SMTP using aiosmtplib."""
        try:
            import aiosmtplib

            msg = self._compose_email(to_email, to_name, subject, body, reply_to)

            if SMTP_USE_TLS:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    username=SMTP_USERNAME or None,
                    password=SMTP_PASSWORD or None,
                    start_tls=True,
                    timeout=30,
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    timeout=30,
                )

            return EmailDeliveryResult(
                success=True,
                message=f"Email sent to {to_email}",
                smtp_response="250 OK",
            )

        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"SMTP send failed: {e}",
                message=f"Could not send email to {to_email}",
            )

    async def _send_via_sendgrid(
        self, to_email: str, subject: str, body: str, reply_to: str
    ) -> EmailDeliveryResult:
        """Send via SendGrid API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {SENDGRID_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": to_email}]}],
                        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
                        "reply_to": {"email": reply_to},
                        "subject": subject,
                        "content": [{"type": "text/plain", "value": body}],
                    },
                )

                if resp.status_code in (200, 201, 202):
                    return EmailDeliveryResult(
                        success=True,
                        message=f"Email sent to {to_email} via SendGrid",
                        smtp_response=f"HTTP {resp.status_code}",
                    )
                else:
                    error_body = resp.text[:500]
                    return EmailDeliveryResult(
                        success=False,
                        error=f"SendGrid API error {resp.status_code}: {error_body}",
                    )

        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"SendGrid send failed: {e}",
            )

    async def _send_via_mailgun(
        self, to_email: str, subject: str, body: str, reply_to: str
    ) -> EmailDeliveryResult:
        """Send via Mailgun API."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                    auth=("api", MAILGUN_API_KEY),
                    data={
                        "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                        "to": to_email,
                        "subject": subject,
                        "text": body,
                        "h:Reply-To": reply_to,
                    },
                )

                if resp.status_code in (200, 201, 202):
                    return EmailDeliveryResult(
                        success=True,
                        message=f"Email sent to {to_email} via Mailgun",
                        smtp_response=f"HTTP {resp.status_code}",
                    )
                else:
                    return EmailDeliveryResult(
                        success=False,
                        error=f"Mailgun API error {resp.status_code}: {resp.text[:500]}",
                    )

        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"Mailgun send failed: {e}",
            )


    def _compose_multipart_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        reply_to: str,
    ) -> MIMEMultipart:
        """Compose a multipart/alternative email with plain-text and HTML versions."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["X-Mailer"] = "NYC Bridge (https://nyc-bridge.local)"

        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        return msg

    async def send_digest(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        body_html: str,
        reply_to: str = "",
    ) -> EmailDeliveryResult:
        """Send a digest email (HTML + plain-text multipart) to a Council office.

        Applies both the global rate limit and the per-domain rate limit for
        recipient mail servers.
        """
        await self._rate_limit()
        await self._domain_rate_limit(to_email)

        msg = self._compose_multipart_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            reply_to=reply_to,
        )

        if SENDGRID_API_KEY:
            return await self._send_via_sendgrid_msg(to_email, subject, msg, reply_to)

        if MAILGUN_API_KEY and MAILGUN_DOMAIN:
            return await self._send_via_mailgun_msg(to_email, subject, body_text, reply_to, body_html)

        return await self._send_via_smtp_msg(to_email, to_name, msg)

    async def _send_via_smtp_msg(
        self,
        to_email: str,
        to_name: str,
        msg: MIMEMultipart,
    ) -> EmailDeliveryResult:
        """Send a pre-composed message via SMTP."""
        try:
            import aiosmtplib

            if SMTP_USE_TLS:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    username=SMTP_USERNAME or None,
                    password=SMTP_PASSWORD or None,
                    start_tls=True,
                    timeout=30,
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    timeout=30,
                )

            return EmailDeliveryResult(
                success=True,
                message=f"Digest sent to {to_email}",
                smtp_response="250 OK",
            )
        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"SMTP digest send failed: {e}",
                message=f"Could not send digest to {to_email}",
            )

    async def _send_via_sendgrid_msg(
        self, to_email: str, subject: str, msg: MIMEMultipart, reply_to: str
    ) -> EmailDeliveryResult:
        """Send a pre-composed message via SendGrid API."""
        try:
            import httpx

            body_text = ""
            body_html = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                elif part.get_content_type() == "text/html":
                    body_html = part.get_payload(decode=True).decode("utf-8", errors="replace")

            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": FROM_EMAIL, "name": FROM_NAME},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": body_text},
                ],
            }
            if body_html:
                payload["content"].append({"type": "text/html", "value": body_html})
            if reply_to:
                payload["reply_to"] = {"email": reply_to}

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {SENDGRID_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if resp.status_code in (200, 201, 202):
                    return EmailDeliveryResult(
                        success=True,
                        message=f"Digest sent to {to_email} via SendGrid",
                        smtp_response=f"HTTP {resp.status_code}",
                    )
                else:
                    error_body = resp.text[:500]
                    return EmailDeliveryResult(
                        success=False,
                        error=f"SendGrid API error {resp.status_code}: {error_body}",
                    )
        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"SendGrid digest send failed: {e}",
            )

    async def _send_via_mailgun_msg(
        self, to_email: str, subject: str, body_text: str, reply_to: str, body_html: str = ""
    ) -> EmailDeliveryResult:
        """Send a pre-composed message via Mailgun API."""
        try:
            import httpx

            data: dict = {
                "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                "to": to_email,
                "subject": subject,
                "text": body_text,
            }
            if reply_to:
                data["h:Reply-To"] = reply_to
            if body_html:
                data["html"] = body_html

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                    auth=("api", MAILGUN_API_KEY),
                    data=data,
                )

                if resp.status_code in (200, 201, 202):
                    return EmailDeliveryResult(
                        success=True,
                        message=f"Digest sent to {to_email} via Mailgun",
                        smtp_response=f"HTTP {resp.status_code}",
                    )
                else:
                    return EmailDeliveryResult(
                        success=False,
                        error=f"Mailgun API error {resp.status_code}: {resp.text[:500]}",
                    )
        except Exception as e:
            return EmailDeliveryResult(
                success=False,
                error=f"Mailgun digest send failed: {e}",
            )


# Singleton
_email_sender: Optional[EmailSender] = None


def get_email_sender() -> EmailSender:
    global _email_sender
    if _email_sender is None:
        _email_sender = EmailSender()
    return _email_sender
