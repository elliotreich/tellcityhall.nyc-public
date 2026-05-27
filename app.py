"""
Civic Bridge — Web Application
Connecting Americans directly to their representatives.
"""
import asyncio, sys, json
from pathlib import Path
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from engine.address_validator import validate_and_lookup, Representative
from engine.yaml_parser import UserContext, load_form, validate_form
from engine.form_submitter import FormSubmitter

app = FastAPI(title="Civic Bridge")
app.mount("/static", StaticFiles(directory="static"), name="static")

_submitter: FormSubmitter | None = None


async def get_submitter() -> FormSubmitter:
    global _submitter
    if _submitter is None:
        _submitter = FormSubmitter()
        await _submitter.start()
    return _submitter


@app.on_event("shutdown")
async def shutdown():
    global _submitter
    if _submitter:
        await _submitter.stop()


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=(Path(__file__).parent / "templates" / "index.html").read_text())


@app.get("/api/autocomplete")
async def address_autocomplete(q: str = Query("", min_length=3)):
    """Address autocomplete using Census Geocoder."""
    if len(q) < 3:
        return JSONResponse({"suggestions": []})

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                params={
                    "address": q,
                    "benchmark": "Public_AR_Current",
                    "format": "json",
                }
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return JSONResponse({"suggestions": []})

    suggestions = []
    for match in data.get("result", {}).get("addressMatches", []):
        addr = match.get("matchedAddress", "")
        if addr and addr not in suggestions:
            suggestions.append(addr)

    return JSONResponse({"suggestions": suggestions[:5]})


@app.post("/api/preview")
async def preview_message(
    message: str = Form(...),
    address: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    topic: str = Form("Other"),
    send_to: str = Form("all"),  # "all", "house", "senate"
):
    if not message.strip() or not address.strip():
        return JSONResponse({"error": "Message and address required."}, status_code=400)

    lookup = await validate_and_lookup(address)
    if not lookup.representatives:
        return JSONResponse({"error": "Could not find your representatives.", "details": lookup.errors}, status_code=400)

    # Filter by chamber if requested
    reps = lookup.representatives
    if send_to == "house":
        reps = [r for r in reps if r.chamber == "house"]
    elif send_to == "senate":
        reps = [r for r in reps if r.chamber == "senate"]

    if not reps:
        return JSONResponse({"error": f"No {send_to} representatives found for this address."}, status_code=400)

    # Load phone numbers
    import yaml
    phones = {}
    with open(Path(__file__).parent / "data" / "congress-legislators" / "legislators-current.yaml") as f:
        leg_data = yaml.safe_load(f)
    for m in leg_data:
        bio = m.get("id", {}).get("bioguide", "")
        for term in m.get("terms", []):
            if term.get("end", "") >= "2026-01-01":
                ph = term.get("phone", "")
                if ph:
                    phones[bio] = ph
                break

    result_reps = []
    captchas_needed = []
    seen_sitekeys = set()

    for r in reps:
        captcha = _detect_captcha(r.bioguide)
        sk = captcha["sitekey"]
        if sk and sk not in seen_sitekeys:
            seen_sitekeys.add(sk)
            captchas_needed.append({
                "type": captcha["type"],
                "sitekey": sk,
                "representatives": [r.name],
            })

        result_reps.append({
            "bioguide": r.bioguide,
            "name": r.name,
            "chamber": r.chamber,
            "state": r.state,
            "party": r.party,
            "phone": phones.get(r.bioguide, ""),
            "captcha": captcha,
            "has_yaml": r.has_yaml,
        })

    return JSONResponse({
        "address": lookup.address.standardized or address,
        "representatives": result_reps,
        "captchas_needed": captchas_needed,
        "warnings": lookup.errors,
        "auto_submit": len(captchas_needed) == 0,
    })


@app.post("/api/send")
async def send_message(
    message: str = Form(...),
    address: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    topic: str = Form("Other"),
    send_to: str = Form("all"),
    captcha_tokens: str = Form(""),
):
    if not message.strip() or not address.strip():
        return JSONResponse({"error": "Message and address required."}, status_code=400)

    tokens = {}
    if captcha_tokens:
        try:
            tokens = json.loads(captcha_tokens)
        except Exception:
            pass

    lookup = await validate_and_lookup(address)
    if not lookup.representatives:
        return JSONResponse({"error": "No representatives found.", "details": lookup.errors}, status_code=400)

    reps = lookup.representatives
    if send_to == "house":
        reps = [r for r in reps if r.chamber == "house"]
    elif send_to == "senate":
        reps = [r for r in reps if r.chamber == "senate"]

    addr = lookup.address
    ctx = UserContext(
        first_name=first_name or "Constituent",
        last_name=last_name or "",
        email=email or "",
        address_street=addr.street or address,
        address_city=addr.city,
        address_state=addr.state,
        address_zip5=addr.zip5,
        address_zip4=addr.zip4,
        topic=topic,
        subject=f"Constituent message: {topic}",
        message=message,
    )

    submitter = await get_submitter()
    results = []

    for rep in reps:
        form_def = load_form(rep.bioguide)
        rep_result = {
            "bioguide": rep.bioguide,
            "name": rep.name,
            "chamber": rep.chamber,
            "state": rep.state,
            "status": "skipped",
            "error": "",
        }

        if not form_def:
            rep_result["status"] = "no_form"
            rep_result["error"] = "No form definition available"
        else:
            issues = validate_form(form_def)
            if issues:
                rep_result["status"] = "skipped"
                rep_result["error"] = f"Form issues: {'; '.join(issues)}"
            else:
                captcha = _detect_captcha(rep.bioguide)
                if captcha["needed"] and captcha["sitekey"]:
                    token = tokens.get(captcha["sitekey"], "")
                    if not token:
                        rep_result["status"] = "captcha_needed"
                        rep_result["error"] = f"Requires verification"
                        results.append(rep_result)
                        continue

                submission = await submitter.submit(form_def, ctx)
                rep_result["status"] = "delivered" if submission.success else "failed"
                rep_result["error"] = submission.error or ""

        results.append(rep_result)

    return JSONResponse({
        "address": addr.standardized or address,
        "representatives": results,
        "warnings": lookup.errors,
    })


def _detect_captcha(bioguide: str) -> dict:
    form = load_form(bioguide)
    if not form:
        return {"type": "unknown", "sitekey": "", "needed": False}

    KNOWN_SITEKEYS = {
        "6Le2KP8SAAAAAA38fpHcO6WgjGaZZrtSNyxfzxkm": "recaptcha_v2",
        "48c6c3f2-b426-4532-bf4e-de4207b26d72": "hcaptcha",
    }

    raw_str = str(form.raw_yaml)
    for sitekey, captcha_type in KNOWN_SITEKEYS.items():
        if sitekey in raw_str:
            return {"type": captcha_type, "sitekey": sitekey, "needed": True}

    if any(s.step_type == "recaptcha" for s in form.steps):
        return {"type": "recaptcha_v2", "sitekey": "", "needed": True}

    if form.captcha_type:
        return {"type": form.captcha_type, "sitekey": form.captcha_sitekey, "needed": True}

    return {"type": "none", "sitekey": "", "needed": False}
