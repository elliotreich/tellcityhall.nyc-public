#!/usr/bin/env python3
"""
NYC Bridge CLI — Contact your NYC elected officials from the command line.

Usage:
    python router.py "160 Water St, New York, NY 10038" \\
        --first-name "Jane" --last-name "Smith" --email "jane@example.com" \\
        --message "I support more bike lanes in my neighborhood." \\
        --topic "Transportation"

Outputs a delivery report to stdout.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from engine.nyc_address_resolver import validate_and_resolve
from engine.nyc_officials import get_officials_for_address
from engine.email_sender import get_email_sender


async def main():
    parser = argparse.ArgumentParser(
        description="NYC Bridge — Contact your NYC elected officials"
    )
    parser.add_argument("address", help="Your NYC street address")
    parser.add_argument("--message", "-m", required=True, help="Your message to elected officials")
    parser.add_argument("--first-name", dest="first_name", default="", help="Your first name")
    parser.add_argument("--last-name", dest="last_name", default="", help="Your last name")
    parser.add_argument("--email", "-e", default="", help="Your email address")
    parser.add_argument("--phone", "-p", default="", help="Your phone number (optional)")
    parser.add_argument("--topic", "-t", default="Other", help="Message topic")
    parser.add_argument("--subject", "-s", default="", help="Message subject")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't send")

    args = parser.parse_args()

    # Validate inputs
    if not args.message.strip():
        print("Error: --message is required", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and (not args.first_name or not args.last_name or not args.email):
        print("Error: --first-name, --last-name, and --email are required for sending", file=sys.stderr)
        sys.exit(1)

    # Resolve address
    if not args.json:
        print(f"Looking up: {args.address}")
        print()

    result = await validate_and_resolve(args.address)

    if result.errors:
        for err in result.errors:
            print(f"  Error: {err}", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"  Address: {result.address.standardized}")
        print(f"  Borough: {result.borough_code.replace('_', ' ').title() if result.borough_code else 'Unknown'}")
        print(f"  Council District: {result.council_district}")
        print(f"  NYS Senate District: {result.state_senate_district}")
        print(f"  NYS Assembly District: {result.state_assembly_district}")
        print()

    # Get officials
    officials = get_officials_for_address(
        council_district=result.council_district,
        borough_code=result.borough_code,
        state_senate_district=result.state_senate_district,
        state_assembly_district=result.state_assembly_district,
    )

    if not args.json:
        print(f"Found {len(officials)} elected officials:")
        print()
        for o in officials:
            badge = "[EMAIL]" if o.contact_method == "email" else "[FORM]"
            print(f"  {badge} {o.title}")
            print(f"        {o.name} ({o.party})")
            if o.email:
                print(f"        {o.email}")
            if o.phone:
                print(f"        {o.phone}")
            if o.note:
                print(f"        Note: {o.note}")
            print()

    if args.dry_run:
        if not args.json:
            print("Dry run — no messages sent.")
        else:
            print(json.dumps({
                "address": result.address.standardized,
                "borough": result.borough_code,
                "council_district": result.council_district,
                "officials": [{"title": o.title, "name": o.name, "email": o.email, "contact_method": o.contact_method} for o in officials],
            }, indent=2))
        return

    # Send
    if not args.json:
        print(f"Sending message to {len(officials)} officials...")
        print()

    email_sender = get_email_sender()
    delivery_results = []
    addr = result.address

    for official in officials:
        start = time.monotonic()

        try:
            if official.contact_method == "email" and official.email:
                email_result = await email_sender.send_email(
                    to_email=official.email,
                    official_title=official.title,
                    official_name=official.name,
                    first_name=args.first_name,
                    last_name=args.last_name,
                    address_street=addr.street or addr.standardized,
                    address_city=addr.city,
                    address_state=addr.state,
                    address_zip=addr.zip5,
                    user_email=args.email,
                    topic=args.topic,
                    message=args.message,
                    subject_override=args.subject or "",
                )
                duration = time.monotonic() - start
                status = "sent" if email_result.success else "failed"
                detail = email_result.message if email_result.success else email_result.error

            elif official.contact_method == "form" and official.email:
                # Form fallback via email
                email_result = await email_sender.send_email(
                    to_email=official.email,
                    official_title=official.title,
                    official_name=official.name,
                    first_name=args.first_name,
                    last_name=args.last_name,
                    address_street=addr.street or addr.standardized,
                    address_city=addr.city,
                    address_state=addr.state,
                    address_zip=addr.zip5,
                    user_email=args.email,
                    topic=args.topic,
                    message=args.message,
                    subject_override=args.subject or "",
                )
                duration = time.monotonic() - start
                status = "sent" if email_result.success else "failed"
                detail = email_result.message if email_result.success else email_result.error

            else:
                duration = time.monotonic() - start
                status = "skipped"
                detail = f"No delivery method available (form: {official.form_key})"

        except Exception as e:
            duration = time.monotonic() - start
            status = "failed"
            detail = str(e)

        delivery_results.append({
            "title": official.title,
            "name": official.name,
            "status": status,
            "detail": detail,
            "duration": round(duration, 1),
        })

        if not args.json:
            icon = "OK" if status == "sent" else "FAIL" if status == "failed" else "SKIP"
            print(f"  [{icon}] {official.title}: {official.name} ({duration:.1f}s)")

    # Summary
    sent = sum(1 for r in delivery_results if r["status"] == "sent")
    failed = sum(1 for r in delivery_results if r["status"] == "failed")

    if args.json:
        print(json.dumps({
            "address": result.address.standardized,
            "results": delivery_results,
            "summary": {"total": len(delivery_results), "sent": sent, "failed": failed},
        }, indent=2))
    else:
        print()
        print(f"Done: {sent} sent, {failed} failed, {len(delivery_results)} total")


if __name__ == "__main__":
    asyncio.run(main())
