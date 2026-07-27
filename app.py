"""
NYC Bridge — FastAPI web application.
Contact all your NYC elected officials with one message.

Endpoints:
  GET  /                  — Serve the single-page web app
  GET  /api/autocomplete  — Address autocomplete via Census Geocoder
  POST /api/preview       — Validate address, return 11 officials + contact info
  POST /api/send          — Deliver message to all officials (email + form)
  GET  /verify/{token}    — Verify a constituent's email address for digest delivery
"""
import json
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import PROJECT_ROOT, FORM_SUBMIT_TIMEOUT, MAX_CONCURRENT_SUBMISSIONS, DELAY_BETWEEN_SUBMISSIONS
from engine.nyc_address_resolver import validate_and_resolve, autocomplete
from engine.nyc_officials import get_officials_for_address, NYCOfficial
from engine.email_sender import get_email_sender
from engine.queue import init_db, verify_message


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialise the digest queue database on startup."""
    init_db()
    yield


app = FastAPI(title="NYC Bridge", version="0.1.0", lifespan=lifespan)

# Static files + templates
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main web application."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/autocomplete")
async def api_autocomplete(q: str = ""):
    """Address autocomplete from Census Geocoder."""
    if len(q.strip()) < 3:
        return JSONResponse({"suggestions": []})

    suggestions = await autocomplete(q)
    return JSONResponse({"suggestions": suggestions})


@app.post("/api/preview")
async def api_preview(
    address: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    message: str = Form(""),
    topic: str = Form("Other"),
):
    """
    Validate address and return the list of officials who will be contacted.
    Returns 11 officials: 3 citywide + 1 council + 2 borough + 3 statewide + 2 state leg.
    """
    if not message or not message.strip():
        return JSONResponse({"error": "Please enter a message."}, status_code=400)

    if not first_name or not last_name:
        return JSONResponse({"error": "Please enter your name."}, status_code=400)

    if not email:
        return JSONResponse({"error": "Please enter your email address."}, status_code=400)

    if not address or not address.strip():
        return JSONResponse({"error": "Please enter your address."}, status_code=400)

    # Validate address and resolve districts
    result = await validate_and_resolve(address)

    if result.errors:
        return JSONResponse({"error": "; ".join(result.errors)}, status_code=400)

    # Get all officials
    officials = get_officials_for_address(
        council_district=result.council_district,
        borough_code=result.borough_code,
        state_senate_district=result.state_senate_district,
        state_assembly_district=result.state_assembly_district,
    )

    # Serialize officials for the frontend
    preview_data = []
    for o in officials:
        preview_data.append({
            "title": o.title,
            "name": o.name,
            "party": o.party,
            "contact_method": o.contact_method,
            "email": o.email or "",
            "form_key": o.form_key or "",
            "phone": o.phone or "",
            "jurisdiction": o.jurisdiction,
            "note": o.note or "",
        })

    return JSONResponse({
        "address": result.address.standardized,
        "borough": result.borough_code.replace("_", " ").title() if result.borough_code else "",
        "council_district": result.council_district,
        "state_senate_district": result.state_senate_district,
        "state_assembly_district": result.state_assembly_district,
        "officials": preview_data,
        "count": len(preview_data),
    })


@app.post("/api/send")
async def api_send(
    address: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    message: str = Form(""),
    topic: str = Form("Other"),
    subject: str = Form(""),
):
    """
    Deliver the message to all officials.
    Email-based officials get an SMTP email.
    Form-based officials get Playwright form submission.
    """
    if not message or not message.strip():
        return JSONResponse({"error": "Please enter a message."}, status_code=400)

    if not first_name or not last_name:
        return JSONResponse({"error": "Please enter your name."}, status_code=400)

    if not email:
        return JSONResponse({"error": "Please enter your email address."}, status_code=400)

    if not address or not address.strip():
        return JSONResponse({"error": "Please enter your address."}, status_code=400)

    # Validate address
    result = await validate_and_resolve(address)
    if result.errors:
        return JSONResponse({"error": "; ".join(result.errors)}, status_code=400)

    # Get all officials
    officials = get_officials_for_address(
        council_district=result.council_district,
        borough_code=result.borough_code,
        state_senate_district=result.state_senate_district,
        state_assembly_district=result.state_assembly_district,
    )

    if not officials:
        return JSONResponse({"error": "No officials found for this address."}, status_code=400)

    # Deliver to each official
    email_sender = get_email_sender()
    delivery_results = []

    for official in officials:
        start_time = time.monotonic()

        try:
            if official.contact_method == "email":
                # Email delivery
                addr = result.address
                email_result = await email_sender.send_email(
                    to_email=official.email,
                    official_title=official.title,
                    official_name=official.name,
                    first_name=first_name,
                    last_name=last_name,
                    address_street=addr.street or addr.standardized,
                    address_city=addr.city,
                    address_state=addr.state,
                    address_zip=addr.zip5,
                    user_email=email,
                    topic=topic,
                    message=message,
                    subject_override=subject or "",
                )

                duration = time.monotonic() - start_time
                delivery_results.append({
                    "title": official.title,
                    "name": official.name,
                    "contact_method": "email",
                    "status": "sent" if email_result.success else "failed",
                    "detail": email_result.message,
                    "error": email_result.error,
                    "duration": round(duration, 1),
                    "email_sent_to": official.email if email_result.success else "",
                    "phone": official.phone,
                })

            elif official.contact_method == "form" and official.form_key:
                # Form-based delivery — attempt Playwright submission
                # For now, fall back to email if email is available, or mark as needs_manual
                if official.email:
                    addr = result.address
                    email_result = await email_sender.send_email(
                        to_email=official.email,
                        official_title=official.title,
                        official_name=official.name,
                        first_name=first_name,
                        last_name=last_name,
                        address_street=addr.street or addr.standardized,
                        address_city=addr.city,
                        address_state=addr.state,
                        address_zip=addr.zip5,
                        user_email=email,
                        topic=topic,
                        message=message,
                        subject_override=subject or "",
                    )
                    duration = time.monotonic() - start_time
                    delivery_results.append({
                        "title": official.title,
                        "name": official.name,
                        "contact_method": "email_fallback",
                        "status": "sent" if email_result.success else "failed",
                        "detail": f"Form ({official.form_key}) not yet automated; sent via email fallback." if email_result.success else email_result.message,
                        "error": email_result.error,
                        "duration": round(duration, 1),
                        "email_sent_to": official.email if email_result.success else "",
                        "phone": official.phone,
                    })
                else:
                    duration = time.monotonic() - start_time
                    delivery_results.append({
                        "title": official.title,
                        "name": official.name,
                        "contact_method": "form",
                        "status": "manual_redirect",
                        "detail": f"Please contact this official via their website form.",
                        "url": official.url,
                        "duration": round(duration, 1),
                        "phone": official.phone,
                    })

            else:
                duration = time.monotonic() - start_time
                delivery_results.append({
                    "title": official.title,
                    "name": official.name,
                    "contact_method": "unknown",
                    "status": "skipped",
                    "detail": "No contact method available.",
                    "duration": round(duration, 1),
                    "phone": official.phone,
                })

        except Exception as e:
            duration = time.monotonic() - start_time
            delivery_results.append({
                "title": official.title,
                "name": official.name,
                "contact_method": official.contact_method,
                "status": "failed",
                "detail": str(e),
                "error": traceback.format_exc()[:500],
                "duration": round(duration, 1),
                "phone": official.phone,
            })

    # Summary
    sent = sum(1 for r in delivery_results if r["status"] == "sent")
    failed = sum(1 for r in delivery_results if r["status"] == "failed")
    manual = sum(1 for r in delivery_results if r["status"] == "manual_redirect")
    skipped = sum(1 for r in delivery_results if r["status"] == "skipped")

    return JSONResponse({
        "address": result.address.standardized,
        "borough": result.borough_code.replace("_", " ").title() if result.borough_code else "",
        "officials": delivery_results,
        "summary": {
            "total": len(delivery_results),
            "sent": sent,
            "failed": failed,
            "manual_redirect": manual,
            "skipped": skipped,
        },
    })


@app.get("/verify/{token}")
async def verify_email(token: str):
    """
    Verify a constituent's email address via a token link.

    Tokens are generated when a message is enqueued.  Unverified messages are
    never included in a digest (prevents blocking the domain with unconfirmed
    submissions).
    """
    from engine.queue import get_message_by_token

    message = get_message_by_token(token)
    if not message:
        return HTMLResponse(
            "<h1>Invalid or expired verification link.</h1>"
            "<p>This token was not found. It may have already been used or the link is incorrect.</p>",
            status_code=404,
        )

    if message.get("verified"):
        return HTMLResponse(
            "<h1>Email already verified.</h1>"
            "<p>Your email was confirmed earlier. Your message will be included in the next digest.</p>"
        )

    success = verify_message(token)
    if success:
        return HTMLResponse(
            "<h1>Email verified!</h1>"
            "<p>Your message has been confirmed and will be included in the next "
            "digest for your Council district. Thank you.</p>"
        )

    return HTMLResponse(
        "<h1>Verification failed.</h1>"
        "<p>Something went wrong. Please try the link again or resubmit your message.</p>",
        status_code=500,
    )
