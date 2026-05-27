#!/usr/bin/env python3
"""
Civic Bridge — Universal Congressional Message Router.

Usage:
    python router.py "160 Water St, New York, NY 10038" --message "My thoughts on..."

    python router.py --address "290 Broadway, Suite 291, New York, NY 10007" \\
                     --first "Jane" --last "Smith" --email "jane@example.com" \\
                     --subject "Climate Policy" --message "I urge you to..."

Flow:
    Address → Validate → Find Representatives → Submit to Each → Report
"""
import asyncio
import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

from engine.address_validator import (
    validate_and_lookup, AddressResult, Representative,
    validate_email as check_email, validate_phone as check_phone
)
from engine.yaml_parser import UserContext, load_form, validate_form, get_form_summary
from engine.form_submitter import FormSubmitter, SubmissionResult
from config import DEFAULT_PREFIX, DEFAULT_TOPIC, DEFAULT_SUBJECT, MAX_CONCURRENT_SUBMISSIONS


# ---- Data Models ----

@dataclass
class DeliveryReport:
    """Complete delivery report for one message to all representatives."""
    address: str
    validated_address: str = ""
    representatives: list["RepDeliveryResult"] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    skip_count: int = 0

    @property
    def total(self) -> int:
        return self.success_count + self.fail_count + self.skip_count


@dataclass
class RepDeliveryResult:
    """Delivery result for a single representative."""
    bioguide: str
    name: str
    chamber: str
    state: str
    status: str  # "delivered", "failed", "skipped", "no_form"
    error: str = ""
    duration: float = 0.0
    captcha_needed: bool = False


# ---- Main Router ----

class CivicBridge:
    """Main router that orchestrates address lookup + form submission."""

    def __init__(self):
        self.submitter: Optional[FormSubmitter] = None

    async def start(self):
        """Initialize the browser engine."""
        self.submitter = FormSubmitter()
        await self.submitter.start()

    async def stop(self):
        """Clean up."""
        if self.submitter:
            await self.submitter.stop()

    async def send(
        self,
        address: str,
        message: str,
        *,
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        phone: str = "",
        prefix: str = DEFAULT_PREFIX,
        subject: str = "",
        topic: str = DEFAULT_TOPIC,
    ) -> DeliveryReport:
        """
        Send a message to all representatives for a given address.

        Args:
            address: Full street address
            message: Message body
            first_name, last_name, email, phone, prefix: Sender info
            subject: Message subject (defaults to generic)
            topic: Issue category (defaults to "Other")

        Returns:
            DeliveryReport with per-representative status
        """
        report = DeliveryReport(address=address)

        # 1. Validate address and find representatives
        print(f"Looking up: {address}")
        lookup = await validate_and_lookup(address)
        report.validated_address = lookup.address.standardized or address
        report.errors.extend(lookup.errors)

        if not lookup.representatives:
            report.errors.append("No representatives found for this address.")
            return report

        print(f"Found {len(lookup.representatives)} representative(s)")
        for r in lookup.representatives:
            status = "ready"
            info = ""
            if r.is_vacant:
                info = " (VACANT - staff may still process)"
            elif r.is_delegate:
                info = " (non-voting delegate)"
            print(f"  {r.chamber.upper()}: {r.name} [{r.bioguide}] {info}")

        # 2. Build user context
        context = _build_context(
            lookup, first_name, last_name, email, phone,
            prefix, subject or DEFAULT_SUBJECT, topic, message
        )

        # 3. Submit to each representative
        if self.submitter is None:
            report.errors.append("Submitter not started. Call start() first.")
            return report

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBMISSIONS)

        async def deliver(rep: Representative) -> RepDeliveryResult:
            async with semaphore:
                return await self._deliver_one(rep, context)

        tasks = [deliver(r) for r in lookup.representatives]
        results = await asyncio.gather(*tasks)

        for r in results:
            report.representatives.append(r)
            if r.status == "delivered":
                report.success_count += 1
            elif r.status == "skipped":
                report.skip_count += 1
            else:
                report.fail_count += 1

        return report

    async def _deliver_one(
        self, rep: Representative, context: UserContext
    ) -> RepDeliveryResult:
        """Attempt delivery to a single representative."""
        result = RepDeliveryResult(
            bioguide=rep.bioguide,
            name=rep.name,
            chamber=rep.chamber,
            state=rep.state,
            status="failed",
        )

        # Check for YAML definition
        form = load_form(rep.bioguide)
        if form is None:
            result.status = "no_form"
            result.error = f"No form YAML available for {rep.name} ({rep.bioguide})"
            return result

        # Validate the form
        issues = validate_form(form)
        if issues:
            result.status = "skipped"
            result.error = f"Form has issues: {'; '.join(issues)}"
            return result

        # Check captcha
        if form.has_required_captcha:
            result.captcha_needed = True
            result.error = f"Form requires {form.captcha_type} captcha - needs solving service"
            # Don't skip - still try to submit (some captchas may not be enforced)

        # Submit
        print(f"  Submitting to {rep.name} ({rep.bioguide})...")
        submission = await self.submitter.submit(form, context)
        result.duration = submission.duration_seconds

        if submission.success:
            result.status = "delivered"
        else:
            result.status = "failed"
            result.error = submission.error or "Form submission failed"

        return result


def _build_context(
    lookup: AddressResult,
    first_name: str, last_name: str,
    email: str, phone: str,
    prefix: str, subject: str, topic: str, message: str,
) -> UserContext:
    """Build a UserContext from validated address data."""
    addr = lookup.address

    # Determine state from representatives if not set
    state = addr.state
    state_full = addr.state_full
    if not state and lookup.representatives:
        state = lookup.representatives[0].state
        state_full = lookup.representatives[0].state

    return UserContext(
        prefix=prefix or DEFAULT_PREFIX,
        first_name=first_name or "Constituent",
        last_name=last_name or "",
        address_street=addr.street or lookup.address,
        address_street_2=addr.street2,
        address_city=addr.city,
        address_state=state,
        address_state_full=state_full,
        address_zip5=addr.zip5,
        address_zip4=addr.zip4,
        phone=phone,
        email=email,
        topic=topic,
        subject=subject,
        message=message,
    )


# ---- CLI ----

def main():
    parser = argparse.ArgumentParser(
        description="Civic Bridge — Send messages to your congressional representatives"
    )
    parser.add_argument("address", nargs="?", help="Your full street address")
    parser.add_argument("--address", "-a", dest="addr_opt", help="Your full street address")
    parser.add_argument("--message", "-m", required=True, help="Your message to send")
    parser.add_argument("--first", help="First name")
    parser.add_argument("--last", help="Last name")
    parser.add_argument("--email", help="Your email address")
    parser.add_argument("--phone", help="Your phone number")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Name prefix")
    parser.add_argument("--subject", help="Message subject")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Issue category")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    address = args.address or args.addr_opt

    if not address:
        parser.error("Address is required")

    if not args.first or not args.last:
        print("Warning: No name provided. Using placeholder names.", file=sys.stderr)

    # Validate inputs
    if args.email and not check_email(args.email):
        parser.error(f"Invalid email: {args.email}")
    if args.phone and not check_phone(args.phone):
        parser.error(f"Invalid phone: {args.phone}")

    async def run():
        bridge = CivicBridge()
        await bridge.start()
        try:
            report = await bridge.send(
                address=address,
                message=args.message,
                first_name=args.first or "",
                last_name=args.last or "",
                email=args.email or "",
                phone=args.phone or "",
                prefix=args.prefix,
                subject=args.subject or "",
                topic=args.topic,
            )
        finally:
            await bridge.stop()
        return report

    report = asyncio.run(run())

    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2))
    else:
        _print_report(report)


def _print_report(report: DeliveryReport):
    """Pretty-print a delivery report."""
    print()
    print("=" * 60)
    print("  CIVIC BRIDGE — DELIVERY REPORT")
    print("=" * 60)
    print(f"  Address: {report.address}")
    if report.validated_address != report.address:
        print(f"  Validated: {report.validated_address}")
    print(f"  Results: {report.success_count} delivered, "
          f"{report.fail_count} failed, {report.skip_count} skipped")
    print("-" * 60)

    for r in report.representatives:
        icon = {"delivered": "✓", "failed": "✗", "skipped": "⊘", "no_form": "?"}.get(r.status, "?")
        print(f"  {icon} {r.name} ({r.chamber.upper()}-{r.state}) — {r.status}")
        if r.error:
            print(f"     Error: {r.error}")
        if r.duration:
            print(f"     Duration: {r.duration:.1f}s")
        if r.captcha_needed:
            print(f"     ⚠ Captcha required")

    if report.errors:
        print("-" * 60)
        print("  Warnings:")
        for e in report.errors:
            print(f"    • {e}")
    print("=" * 60)


def _report_to_dict(report: DeliveryReport) -> dict:
    """Convert report to JSON-serializable dict."""
    return {
        "address": report.address,
        "validated_address": report.validated_address,
        "success_count": report.success_count,
        "fail_count": report.fail_count,
        "skip_count": report.skip_count,
        "errors": report.errors,
        "representatives": [
            {
                "name": r.name,
                "bioguide": r.bioguide,
                "chamber": r.chamber,
                "state": r.state,
                "status": r.status,
                "error": r.error,
                "duration": round(r.duration, 1),
                "captcha_needed": r.captcha_needed,
            }
            for r in report.representatives
        ],
    }


if __name__ == "__main__":
    main()
