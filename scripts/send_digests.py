#!/usr/bin/env python3
"""
NYC Bridge — Digest delivery script.

Iterates all 51 City Council districts, builds pending messages into a
daily digest, and sends the digest to the Council member's office.

Safe (idempotent) to run repeatedly: messages transition through
  pending → queued → sent
and the script will never pick up the same message twice.

Usage:
  python scripts/send_digests.py                  # all districts
  python scripts/send_digests.py --district 1      # single district
  python scripts/send_digests.py --dry-run         # render without sending
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so config and engine modules are importable
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import DIGEST_MIN_FOR_SUMMARY
from engine.digest_builder import (
    FallbackSummarizer,
    build_digest_html,
    build_digest_text,
)
from engine.email_sender import get_email_sender
from engine.nyc_officials import _load_officials
from engine.queue import (
    create_digest,
    get_pending_count,
    get_districts_with_pending,
    mark_failed,
    mark_sent,
    pending_for_district,
)


def get_council_member_name(district: int) -> str:
    """Return the name of a Council member by district number."""
    data = _load_officials()
    council = data.get("council", {})
    member = council.get(district)
    return member.get("name", f"District {district}") if member else f"District {district}"


def get_council_member_email(district: int) -> str:
    """Return the email of a Council member by district number."""
    data = _load_officials()
    council = data.get("council", {})
    member = council.get(district)
    return member.get("email", "") if member else ""


async def send_digest_for_district(
    district: int,
    dry_run: bool = False,
) -> dict:
    """
    Build and send the daily digest for one Council district.

    Returns a result dict with keys: district, pending_count, action, error.
    """
    result: dict = {
        "district": district,
        "member_name": get_council_member_name(district),
        "pending_count": 0,
        "digest_id": None,
        "action": "skipped",
        "error": "",
    }

    pending_count = get_pending_count(district, verified_only=True)
    result["pending_count"] = pending_count

    if pending_count == 0:
        return result

    if pending_count < DIGEST_MIN_FOR_SUMMARY:
        include_summary = False
    else:
        include_summary = True

    messages = pending_for_district(district, verified_only=True)
    message_ids = [m["id"] for m in messages]
    member_name = get_council_member_name(district)
    member_email = get_council_member_email(district)

    # Determine reply-to: single constituent → their email; multiple → official
    unique_emails = list(
        {m["sender_email"].strip().lower() for m in messages if m.get("sender_email")}
    )
    if len(unique_emails) == 1:
        reply_to = unique_emails[0]
    else:
        reply_to = get_council_member_email(district)

    # Build summaries (deterministic fallback)
    summarizer = FallbackSummarizer()
    topic_summaries = summarizer.summarize(messages)

    # Render digest
    body_text = build_digest_text(
        district=district,
        council_member_name=member_name,
        messages=messages,
        topic_summaries=topic_summaries,
        include_summary=include_summary,
    )

    body_html = build_digest_html(
        district=district,
        council_member_name=member_name,
        messages=messages,
        topic_summaries=topic_summaries,
        include_summary=include_summary,
    )

    subject = f"Constituent Message Digest — Council District {district}"

    if dry_run:
        result["action"] = "dry_run"
        result["subject"] = subject
        result["text_preview"] = body_text[:500]
        result["to_email"] = member_email
        result["reply_to"] = reply_to
        return result

    # Create digest (transition messages to 'queued')
    digest_id = create_digest(district, message_ids)
    result["digest_id"] = digest_id

    # Send
    if not member_email:
        mark_failed(message_ids, digest_id)
        result["action"] = "failed"
        result["error"] = f"No email found for Council District {district}"
        return result

    email_sender = get_email_sender()
    delivery = await email_sender.send_digest(
        to_email=member_email,
        to_name=member_name,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        reply_to=reply_to,
    )

    if delivery.success:
        mark_sent(message_ids, digest_id)
        result["action"] = "sent"
    else:
        mark_failed(message_ids, digest_id)
        result["action"] = "failed"
        result["error"] = delivery.error

    return result


async def main_async(args):
    """Async main body."""
    if args.district:
        districts = [args.district]
    else:
        districts = sorted(get_districts_with_pending(verified_only=True))
        if not districts:
            print("No districts with pending messages.")
            return

    results = []
    for d in districts:
        r = await send_digest_for_district(district=d, dry_run=args.dry_run)
        results.append(r)

        if r["action"] == "skipped":
            print(
                f"District {d} ({r['member_name']}): "
                f"{r['pending_count']} pending — skipped"
            )
        elif r["action"] == "dry_run":
            print(f"\n{'=' * 60}")
            print(f"DRY RUN — District {d} ({r['member_name']})")
            print(f"To: {r['to_email']}")
            print(f"Subject: {r['subject']}")
            print(f"Reply-To: {r['reply_to']}")
            print(f"Messages: {r['pending_count']}")
            print(f"Preview:\n{r['text_preview']}")
        elif r["action"] == "sent":
            print(
                f"District {d} ({r['member_name']}): "
                f"{r['pending_count']} messages sent (digest {r['digest_id']})"
            )
        elif r["action"] == "failed":
            print(
                f"District {d} ({r['member_name']}): FAILED — {r['error']}",
                file=sys.stderr,
            )

    # Summary
    sent = sum(1 for r in results if r["action"] == "sent")
    failed = sum(1 for r in results if r["action"] == "failed")
    skipped = sum(1 for r in results if r["action"] == "skipped")
    total_pending = sum(r["pending_count"] for r in results)

    print(
        f"\nSummary: {sent} sent, {failed} failed, "
        f"{skipped} skipped ({total_pending} total pending)"
    )


def main():
    parser = argparse.ArgumentParser(description="Send Council district digests")
    parser.add_argument(
        "--district", type=int, help="Single district to process (1-51)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render digests without sending (prints preview)",
    )
    args = parser.parse_args()

    if args.district and not (1 <= args.district <= 51):
        print(
            f"District must be between 1 and 51, got {args.district}",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
