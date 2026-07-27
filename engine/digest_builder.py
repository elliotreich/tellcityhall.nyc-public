"""
Digest builder for NYC Bridge.

Produces the daily constituent-message digest for a Council district.
Implements the quote-anchored cover page design: every claim in AI prose
must be traceable to a real submitted message, and topic summaries must
include at least one verbatim excerpt from an actual constituent message.
"""
import html as html_module
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import DIGEST_MIN_FOR_SUMMARY

# ---------------------------------------------------------------------------
# Summarizer interface
# ---------------------------------------------------------------------------


@dataclass
class TopicSummary:
    """Summarised view of one topic across multiple constituent messages."""

    topic: str
    message_count: int
    quotes: list[str] = field(default_factory=list)
    prose: str = ""
    """Short AI-generated prose summary (empty when using deterministic fallback)."""


class Summarizer(ABC):
    """Interface for generating per-topic summaries of constituent messages."""

    @abstractmethod
    def summarize(self, messages: list[dict]) -> list[TopicSummary]:
        ...


class FallbackSummarizer(Summarizer):
    """Deterministic summariser that emits only quotes and tallies, no AI prose."""

    def summarize(self, messages: list[dict]) -> list[TopicSummary]:
        """Group messages by topic and extract one representative quote per topic.

        Quotes are verbatim excerpts (first 280 chars) from actual messages.
        """
        by_topic: dict[str, list[dict]] = defaultdict(list)
        for m in messages:
            topic = m.get("topic", "Other")
            by_topic[topic].append(m)

        results: list[TopicSummary] = []
        for topic in sorted(by_topic):
            topic_msgs = by_topic[topic]
            quotes = []
            for m in topic_msgs:
                msg_text = m.get("message", "").strip()
                excerpt = msg_text[:280]
                if len(msg_text) > 280:
                    excerpt += "…"
                if excerpt:
                    quotes.append(excerpt)

            results.append(
                TopicSummary(
                    topic=topic,
                    message_count=len(topic_msgs),
                    quotes=quotes,
                    prose="",
                )
            )
        return results


class LLMSummarizer(Summarizer):
    """Optional summariser that delegates to an LLM and falls back to deterministic.

    The LLM summariser MUST include at least one verbatim quote per topic and
    MUST NOT invent facts.  If the LLM call fails or returns empty content the
    deterministic fallback is used instead.
    """

    def __init__(self, fallback: Optional[Summarizer] = None):
        self._fallback = fallback or FallbackSummarizer()

    def summarize(self, messages: list[dict]) -> list[TopicSummary]:
        """Attempt LLM summarisation; fall back to deterministic on failure."""
        try:
            summaries = self._llm_summarize(messages)
            if summaries and any(s.prose.strip() for s in summaries):
                return summaries
        except Exception:
            pass
        return self._fallback.summarize(messages)

    def _llm_summarize(self, messages: list[dict]) -> list[TopicSummary]:
        """Call the configured LLM to produce topic summaries.

        This stub always falls back to deterministic output.  Subclass or
        monkey-patch to integrate a real LLM provider.
        """
        raise NotImplementedError("LLM summariser is not configured")


# ---------------------------------------------------------------------------
# Digest builders
# ---------------------------------------------------------------------------


def _format_date_range(messages: list[dict]) -> str:
    """Return a human-readable date range for a set of messages."""
    dates = []
    for m in messages:
        ts = m.get("submitted_at", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                dates.append(dt)
            except (ValueError, TypeError):
                continue

    if not dates:
        return ""

    dates.sort()
    fmt = "%B %d, %Y"
    if dates[0].date() == dates[-1].date():
        return dates[0].strftime(fmt)
    return f"{dates[0].strftime(fmt)} — {dates[-1].strftime(fmt)}"


def _extract_domain(email: str) -> str:
    """Return the domain portion of an email address, lowercased."""
    return email.strip().lower().split("@")[-1] if "@" in email else email


def _infer_reply_to(messages: list[dict]) -> str:
    """Determine the Reply-To address for a digest.

    With one constituent, use their email.  With several, use the app sender
    address (the official or a generic address) — individual emails are shown
    beside each message in the digest body.
    """
    unique_emails = list(
        {m.get("sender_email", "").strip().lower() for m in messages if m.get("sender_email")}
    )
    if len(unique_emails) == 1:
        return unique_emails[0]
    return ""  # caller fills in the official's email or a generic address


def build_digest_text(
    district: int,
    council_member_name: str,
    messages: list[dict],
    topic_summaries: Optional[list[TopicSummary]] = None,
    include_summary: bool = True,
) -> str:
    """Build a plain-text digest for a Council district.

    When *include_summary* is True and there are at least DIGEST_MIN_FOR_SUMMARY
    messages the digest starts with a cover page (date, tallies, quotes).
    Otherwise messages are forwarded plainly.
    """
    lines: list[str] = []
    separator = "=" * 72

    # --- Cover page ---
    if include_summary and len(messages) >= DIGEST_MIN_FOR_SUMMARY:
        lines.append(f"Constituent Message Digest — Council District {district}")
        lines.append(f"Council Member: {council_member_name}")
        date_range = _format_date_range(messages)
        if date_range:
            lines.append(f"Messages from: {date_range}")
        lines.append(f"Total messages: {len(messages)}")
        lines.append(separator)

        summaries = topic_summaries or FallbackSummarizer().summarize(messages)

        for ts in summaries:
            lines.append(f"\n{'─' * 60}")
            lines.append(f"Topic: {ts.topic} ({ts.message_count} message{'s' if ts.message_count != 1 else ''})")
            lines.append(f"{'─' * 60}")

            if ts.prose.strip():
                lines.append("")
                lines.append(ts.prose.strip())

            for quote in ts.quotes:
                lines.append("")
                lines.append(f"  > {quote}")

        lines.append(f"\n{separator}")
        lines.append("INDIVIDUAL CONSTITUENT MESSAGES")
        lines.append(separator)
    elif include_summary and len(messages) == 0:
        return ""
    # else: no cover page, just messages

    # --- Individual messages ---
    for i, m in enumerate(messages, 1):
        name = m.get("sender_name", "Anonymous")
        email = m.get("sender_email", "")
        address = m.get("sender_address", "")
        topic = m.get("topic", "Other")
        msg_text = m.get("message", "")

        lines.append(f"\n{'─' * 72}")
        lines.append(f"MESSAGE {i}")
        lines.append(f"From: {name}")
        if email:
            lines.append(f"Email: {email}")
        if address:
            lines.append(f"Address: {address}")
        lines.append(f"Topic: {topic}")
        lines.append(f"{'─' * 72}")
        lines.append("")
        lines.append(msg_text)

    return "\n".join(lines)


def build_digest_html(
    district: int,
    council_member_name: str,
    messages: list[dict],
    topic_summaries: Optional[list[TopicSummary]] = None,
    include_summary: bool = True,
) -> str:
    """Build an HTML digest email for a Council district.

    Page 1 is a cover letter with topic tallies and verbatim constituent
    quotes.  Subsequent pages contain the raw constituent messages.
    """
    parts: list[str] = []
    safe = html_module.escape

    # --- Cover page (only when summarising and >= DIGEST_MIN_FOR_SUMMARY) ---
    show_cover = include_summary and len(messages) >= DIGEST_MIN_FOR_SUMMARY

    if show_cover:
        summaries = topic_summaries or FallbackSummarizer().summarize(messages)
        date_range = _format_date_range(messages)

        cover = [
            '<div style="page-break-after: always; margin-bottom: 2em;">',
            f"<h1>Constituent Message Digest</h1>",
            f"<p><strong>Council District {district}</strong> — {safe(council_member_name)}</p>",
        ]
        if date_range:
            cover.append(f"<p>Messages from: {safe(date_range)}</p>")
        cover.append(f"<p><strong>Total messages:</strong> {len(messages)}</p>")
        cover.append("<hr>")

        for ts in summaries:
            cover.append('<div style="margin: 1.5em 0;">')
            cover.append(
                f"<h2>{safe(ts.topic)} ({ts.message_count} message"
                f"{'s' if ts.message_count != 1 else ''})</h2>"
            )
            if ts.prose.strip():
                cover.append(f"<p>{safe(ts.prose.strip())}</p>")

            for quote in ts.quotes:
                cover.append(
                    f'<blockquote style="border-left: 3px solid #ccc; '
                    f'margin: 0.5em 0 0.5em 1em; padding-left: 1em; '
                    f'color: #444;">'
                    f"{safe(quote)}</blockquote>"
                )
            cover.append("</div>")

        cover.append("<hr>")
        cover.append("<h2>Individual Constituent Messages</h2>")
        cover.append("</div>")
        parts.append("\n".join(cover))

    # --- Individual messages ---
    for i, m in enumerate(messages, 1):
        name = safe(m.get("sender_name", "Anonymous"))
        email = safe(m.get("sender_email", ""))
        address = safe(m.get("sender_address", ""))
        topic = safe(m.get("topic", "Other"))
        msg_text = safe(m.get("message", ""))

        msg_html = [
            f'<div style="margin: 1.5em 0; padding: 1em; border: 1px solid #ddd; '
            f'border-radius: 4px; page-break-inside: avoid;">',
            f"<h3>Message {i}</h3>",
            f"<table style='font-size: 0.95em; border-collapse: collapse;'>",
        ]
        msg_html.append(
            f"<tr><td style='padding: 2px 8px 2px 0; font-weight: bold;'>From:</td>"
            f"<td>{name}</td></tr>"
        )
        if email:
            msg_html.append(
                f"<tr><td style='padding: 2px 8px 2px 0; font-weight: bold;'>Email:</td>"
                f"<td><a href='mailto:{email}'>{email}</a></td></tr>"
            )
        if address:
            msg_html.append(
                f"<tr><td style='padding: 2px 8px 2px 0; font-weight: bold;'>Address:</td>"
                f"<td>{address}</td></tr>"
            )
        msg_html.append(
            f"<tr><td style='padding: 2px 8px 2px 0; font-weight: bold;'>Topic:</td>"
            f"<td>{topic}</td></tr>"
        )
        msg_html.append("</table>")
        msg_html.append(
            f'<div style="margin-top: 1em; white-space: pre-wrap;">{msg_text}</div>'
        )
        msg_html.append("</div>")
        parts.append("\n".join(msg_html))

    body = "\n".join(parts)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                'Helvetica Neue', Arial, sans-serif;
         max-width: 700px; margin: 2em auto; padding: 0 1em;
         line-height: 1.6; color: #222; }}
  h1 {{ font-size: 1.6em; margin-bottom: 0.3em; }}
  h2 {{ font-size: 1.2em; margin: 1.2em 0 0.4em; }}
  h3 {{ font-size: 1.1em; margin: 0 0 0.5em; }}
  hr {{ border: none; border-top: 2px solid #ddd; margin: 1.5em 0; }}
  blockquote {{ font-style: italic; }}
  a {{ color: #2563eb; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
    return full_html
