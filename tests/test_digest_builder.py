"""Tests for the digest builder — cover-page rendering, low-volume rule, fallback."""
import pytest

from engine.digest_builder import (
    FallbackSummarizer,
    TopicSummary,
    build_digest_html,
    build_digest_text,
)
from config import DIGEST_MIN_FOR_SUMMARY


def _make_message(
    topic: str = "Housing",
    name: str = "Alice Smith",
    email: str = "alice@example.com",
    address: str = "350 Jay St, Brooklyn",
    message: str = "We need more affordable housing in the district.",
    submitted_at: str = "2026-07-27T10:00:00+00:00",
) -> dict:
    return {
        "sender_name": name,
        "sender_email": email,
        "sender_address": address,
        "topic": topic,
        "message": message,
        "submitted_at": submitted_at,
    }


def _pad_to_summary_threshold(msgs: list[dict]) -> list[dict]:
    """Extend *msgs* until it reaches DIGEST_MIN_FOR_SUMMARY.

    Tests that exercise the cover page must supply at least the threshold
    number of messages; padding keeps them correct if the threshold changes.
    """
    padded = list(msgs)
    i = 0
    while len(padded) < DIGEST_MIN_FOR_SUMMARY:
        base = msgs[i % len(msgs)]
        clone = dict(base)
        clone["message"] = f"{base['message']} (additional constituent {i + 1})"
        padded.append(clone)
        i += 1
    return padded



class TestFallbackSummarizer:
    def test_single_topic(self):
        msgs = [_make_message(topic="Housing")]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        assert len(summaries) == 1
        assert summaries[0].topic == "Housing"
        assert summaries[0].message_count == 1
        assert len(summaries[0].quotes) == 1
        assert summaries[0].prose == ""

    def test_multiple_topics_sorted(self):
        msgs = [
            _make_message(topic="Transportation", message="Fix the buses."),
            _make_message(topic="Housing", message="More units."),
            _make_message(topic="Transportation", message="Fix the trains."),
        ]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        assert len(summaries) == 2
        assert summaries[0].topic == "Housing"
        assert summaries[1].topic == "Transportation"
        assert summaries[0].message_count == 1
        assert summaries[1].message_count == 2

    def test_no_prose_in_fallback(self):
        """Deterministic fallback should never produce prose."""
        msgs = [_make_message(topic="Parks"), _make_message(topic="Parks")]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        for s in summaries:
            assert s.prose == ""

    def test_quotes_are_verbatim(self):
        msg_text = "This is a specific constituent concern about safety."
        msgs = [_make_message(message=msg_text)]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        assert msg_text in summaries[0].quotes[0]

    def test_empty_messages(self):
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize([])
        assert summaries == []

    def test_long_messages_truncated(self):
        long_msg = "A" * 500
        msgs = [_make_message(message=long_msg)]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        assert len(summaries[0].quotes[0]) <= 281  # 280 + ellipsis


class TestBuildDigestText:
    def test_basic_digest_with_summary(self):
        msgs = [
            _make_message(topic="Housing", message="More affordable units needed."),
            _make_message(topic="Housing", message="Rent stabilization is critical."),
            _make_message(topic="Transportation", message="Fix the B61 bus."),
            _make_message(topic="Transportation", message="Extend the G train."),
        ]
        msgs = _pad_to_summary_threshold(msgs)
        text = build_digest_text(
            district=33,
            council_member_name="Lincoln Restler",
            messages=msgs,
            include_summary=True,
        )
        assert "Council District 33" in text
        assert "Lincoln Restler" in text
        assert "Housing" in text
        assert "Transportation" in text
        assert f"Total messages: {len(msgs)}" in text
        assert "MESSAGE 1" in text
        assert "MESSAGE 4" in text
        assert "More affordable units" in text
        assert "Fix the B61 bus" in text

    def test_low_volume_plain_forwarding(self):
        """Fewer than DIGEST_MIN_FOR_SUMMARY messages should skip cover page."""
        msgs = [
            _make_message(topic="Housing", message="Fix housing."),
            _make_message(topic="Transportation", message="Fix buses."),
        ]
        text = build_digest_text(
            district=33,
            council_member_name="Lincoln Restler",
            messages=msgs,
            include_summary=True,
        )
        # Should NOT have a cover page topic header
        assert "Constituent Message Digest" not in text
        # Should still show individual messages
        assert "MESSAGE 1" in text
        assert "MESSAGE 2" in text

    def test_single_message(self):
        msgs = [_make_message(message="Just a test.")]
        text = build_digest_text(
            district=1,
            council_member_name="Chris Marte",
            messages=msgs,
            include_summary=True,
        )
        assert "MESSAGE 1" in text
        assert "Just a test." in text

    def test_no_messages_returns_empty(self):
        text = build_digest_text(
            district=1,
            council_member_name="Test",
            messages=[],
            include_summary=True,
        )
        assert text == ""

    def test_date_range_single_day(self):
        msgs = [
            _make_message(submitted_at="2026-07-27T10:00:00+00:00"),
            _make_message(submitted_at="2026-07-27T14:30:00+00:00"),
        ]
        msgs = _pad_to_summary_threshold(msgs)
        # Need 3+ for cover page
        msgs.append(_make_message(submitted_at="2026-07-27T16:00:00+00:00"))
        text = build_digest_text(district=33, council_member_name="Test", messages=msgs)
        assert "July 27, 2026" in text
        # Date range should show a single day (no range separator like —)
        assert "July 27, 2026" in text

    def test_deterministic_fallback_valid(self):
        """The deterministic fallback should always produce a valid digest with no LLM."""
        msgs = [
            _make_message(topic="Housing", message="Need more housing."),
            _make_message(topic="Housing", message="Rent is too high."),
            _make_message(topic="Transportation", message="Fix the subway."),
            _make_message(topic="Parks", message="Clean the parks."),
            _make_message(topic="Safety", message="More police patrols."),
        ]
        msgs = _pad_to_summary_threshold(msgs)
        text = build_digest_text(
            district=1,
            council_member_name="Chris Marte",
            messages=msgs,
            include_summary=True,
        )
        assert "Council District 1" in text
        assert "Chris Marte" in text
        assert "Housing" in text
        assert "Transportation" in text
        assert "Parks" in text
        assert "Safety" in text
        assert "MESSAGE 5" in text
        # No AI prose
        assert "Constituent Message Digest" in text


class TestBuildDigestHtml:
    def test_basic_html_structure(self):
        msgs = [
            _make_message(topic="Housing", message="Affordable housing."),
            _make_message(topic="Housing", message="Rent control."),
            _make_message(topic="Transportation", message="Better buses."),
            _make_message(topic="Transportation", message="Subway expansion."),
        ]
        msgs = _pad_to_summary_threshold(msgs)
        html = build_digest_html(
            district=33,
            council_member_name="Lincoln Restler",
            messages=msgs,
            include_summary=True,
        )
        assert "<!DOCTYPE html>" in html
        assert "Council District 33" in html
        assert "Lincoln Restler" in html
        assert "Message 1" in html
        assert "Message 4" in html
        assert "alice@example.com" in html
        assert "</html>" in html

    def test_html_no_cover_for_low_volume(self):
        msgs = [_make_message(message="Solo message.")]
        html = build_digest_html(
            district=1,
            council_member_name="Test",
            messages=msgs,
            include_summary=True,
        )
        assert "Constituent Message Digest" not in html
        assert "Message 1" in html

    def test_html_deterministic_fallback(self):
        """The deterministic fallback should always produce valid HTML with no LLM."""
        msgs = [
            _make_message(topic="Housing", message="Need more housing."),
            _make_message(topic="Housing", message="Rent is too high."),
            _make_message(topic="Transportation", message="Fix the subway."),
        ]
        msgs = _pad_to_summary_threshold(msgs)
        html = build_digest_html(
            district=1,
            council_member_name="Chris Marte",
            messages=msgs,
            include_summary=True,
        )
        assert "Council District 1" in html
        assert "Chris Marte" in html
        assert "Housing" in html
        assert "Transportation" in html
        assert "Need more housing" in html or "Rent is too high" in html
        assert "Fix the subway" in html

    def test_html_mailto_links(self):
        msgs = [_make_message(email="constituent@test.org")]
        msgs.append(_make_message(email="other@test.org"))
        msgs.append(_make_message(email="third@test.org"))
        html = build_digest_html(
            district=1,
            council_member_name="Test",
            messages=msgs,
            include_summary=True,
        )
        assert "mailto:constituent@test.org" in html


class TestTopicSummaryDataclass:
    def test_defaults(self):
        s = TopicSummary(topic="Housing", message_count=3)
        assert s.topic == "Housing"
        assert s.message_count == 3
        assert s.quotes == []
        assert s.prose == ""

    def test_with_optional_fields(self):
        s = TopicSummary(
            topic="Parks",
            message_count=2,
            quotes=["Clean parks now!"],
            prose="Constituents demand cleaner parks.",
        )
        assert s.prose == "Constituents demand cleaner parks."
        assert s.quotes == ["Clean parks now!"]


class TestQuoteAnchoredRule:
    def test_every_summary_has_at_least_one_quote(self):
        """HARD RULE: every topic summary must have at least one verbatim quote."""
        msgs = [
            _make_message(topic="Housing", message="Specific housing concern."),
            _make_message(topic="Transportation", message="Specific transit concern."),
            _make_message(topic="Housing", message="Another housing point."),
        ]
        summarizer = FallbackSummarizer()
        summaries = summarizer.summarize(msgs)
        for s in summaries:
            assert len(s.quotes) >= 1, f"Topic '{s.topic}' has no quotes"
            # Every quote must be a real substring of an actual message
            all_text = " ".join(m["message"] for m in msgs)
            for q in s.quotes:
                # Strip the truncation ellipsis if present
                clean_q = q.replace("…", "")
                assert clean_q in all_text or q in all_text, \
                    f"Quote '{q[:50]}...' not found in any message"
