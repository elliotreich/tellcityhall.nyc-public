"""Tests for per-domain rate limiting in the email sender."""
import asyncio
import time

import pytest

from engine.email_sender import EmailSender
from config import DIGEST_DOMAIN_DELAY


class TestDomainRateLimit:
    def test_extract_domain(self):
        assert EmailSender._extract_domain("user@example.com") == "example.com"
        assert EmailSender._extract_domain("User@Example.COM") == "example.com"
        assert EmailSender._extract_domain("no-at-sign") == "no-at-sign"

    def test_same_domain_enforces_delay(self):
        sender = EmailSender()
        domain = "example.com"

        t0 = time.monotonic()
        sender._domain_last_send[domain] = t0 - DIGEST_DOMAIN_DELAY + 0.1  # almost ready

        async def run():
            await sender._domain_rate_limit("user@example.com")

        asyncio.run(run())
        elapsed = time.monotonic() - t0
        # Should have waited at least 0.1s
        assert elapsed >= 0.09

    def test_different_domains_no_delay(self):
        sender = EmailSender()

        async def run():
            t0 = time.monotonic()
            await sender._domain_rate_limit("user@a.com")
            elapsed_1 = time.monotonic() - t0

            t0_2 = time.monotonic()
            await sender._domain_rate_limit("user@b.com")
            elapsed_2 = time.monotonic() - t0_2

            # Both should complete immediately (< 0.1s)
            assert elapsed_1 < 0.1
            assert elapsed_2 < 0.1

        asyncio.run(run())

    def test_same_domain_back_to_back_waits(self):
        sender = EmailSender()

        async def run():
            await sender._domain_rate_limit("user@same.com")

            t0 = time.monotonic()
            await sender._domain_rate_limit("other@same.com")
            elapsed = time.monotonic() - t0

            assert elapsed >= DIGEST_DOMAIN_DELAY * 0.9  # allow minor scheduling jitter

        asyncio.run(run())

    def test_no_block_on_first_send(self):
        sender = EmailSender()

        async def run():
            t0 = time.monotonic()
            await sender._domain_rate_limit("first@domain.com")
            elapsed = time.monotonic() - t0
            assert elapsed < 0.1  # no prior send, no wait

        asyncio.run(run())

    def test_domain_tracking_independent(self):
        """Domains should have independent timing."""
        sender = EmailSender()

        async def run():
            await sender._domain_rate_limit("a@x.com")
            a_last = sender._domain_last_send.get("x.com", 0)
            assert a_last > 0

            await sender._domain_rate_limit("b@y.com")
            assert "x.com" in sender._domain_last_send
            assert "y.com" in sender._domain_last_send

        asyncio.run(run())

    def test_configurable_delay(self):
        """Should use DIGEST_DOMAIN_DELAY from config."""
        from config import DIGEST_DOMAIN_DELAY as configured_delay
        assert configured_delay == 2.0
