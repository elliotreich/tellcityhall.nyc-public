# Civic Bridge

**Your voice, delivered to Congress.**

Civic Bridge is a nonpartisan civic engagement tool that lets Americans write a message once and have it delivered directly to all three of their congressional representatives — their House member and both Senators — through each representative's official contact form.

---

## How It Works

1. **Write your message** — Type what you want to say to Congress. Pick a topic. Choose whether to send to your Representative, Senators, or both.

2. **Enter your information** — Name and email are required (98% of congressional contact forms demand them). Nothing is shared publicly.

3. **Enter your address** — Type your street address with autocomplete. We validate it against the U.S. Census Bureau's geocoder to determine your congressional district. Nothing is stored.

4. **Confirm & send** — See exactly who your message is going to. If any representative's form requires a CAPTCHA, solve it inline. Get phone numbers and a call script to follow up.

5. **Results** — Delivery status for each representative plus phone numbers to call their office directly.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                    User                          │
│  (message → address → captcha → send)            │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              FastAPI Web App                      │
│  /                    → index.html               │
│  /api/autocomplete    → Census address lookup    │
│  /api/preview         → validate + captcha info  │
│  /api/send            → submit to all reps       │
└────────────────────┬─────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌─────────┐   ┌──────────┐   ┌──────────────┐
│ Census  │   │  Google  │   │ Legislator DB │
│ Geocoder│   │  Civic   │   │ (YAML, 536    │
│ (free)  │   │  (opt)   │   │  members)     │
└─────────┘   └──────────┘   └──────┬────────┘
                                    │
                          ┌─────────▼─────────┐
                          │  YAML Form Engine  │
                          │  (contact-congress │
                          │   789 definitions) │
                          └─────────┬─────────┘
                                    │
                          ┌─────────▼─────────┐
                          │    Playwright      │
                          │  (headless Chrome) │
                          │  fills & submits   │
                          │  each rep's form   │
                          └────────────────────┘
```

### Address Validation
- **Primary**: U.S. Census Bureau Geocoder (free, no API key)
- **Fallback**: Aggressive state extraction from address text, ZIP code prefix lookup, city name matching
- Every valid U.S. street address resolves to the correct House district + 2 Senators

### Form Submission
- Uses the [unitedstates/contact-congress](https://github.com/unitedstates/contact-congress) YAML dataset — 789 form definitions covering every member of Congress
- Each YAML maps a representative's contact form fields to canonical variables (`$NAME_FIRST`, `$MESSAGE`, `$TOPIC`, etc.)
- Playwright (headless Chromium) executes the multi-step form workflow: navigate → fill fields → select dropdowns → solve CAPTCHA → submit → verify success

### CAPTCHA Strategy
- CAPTCHA widgets rendered **inline** on the Civic Bridge page using the representative's sitekey
- User solves them once — tokens reused across representatives sharing the same sitekey
- Only 113 of 536 members require CAPTCHA; most are reCAPTCHA v2 checkbox (one click)

---

## Coverage

| Chamber | Members | YAML Definitions | Status |
|---------|---------|-----------------|--------|
| Senate | 100 | 100 | 100% |
| House (voting) | 430 | 430 | 100% |
| Delegates | 6 | 6 | 100% |
| **Total** | **536** | **536** | **100%** |

---

## Deployment

### Requirements
- Python 3.11+
- Playwright (Chromium)
- Optional: Google Civic API key (for enhanced district lookup), 2captcha API key (for domain-locked captchas)

### Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# Clone form definitions
git clone https://github.com/unitedstates/contact-congress.git data/contact-congress
git clone https://github.com/unitedstates/congress-legislators.git data/congress-legislators

# Run
python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Production (systemd + nginx/caddy)
See the systemd unit at `/etc/systemd/system/civic-bridge.service` on the VPS.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web application |
| GET | `/api/autocomplete?q=...` | Address autocomplete (Census API) |
| POST | `/api/preview` | Validate address, return reps + captcha info |
| POST | `/api/send` | Submit message to all selected representatives |

### POST /api/preview
```
Form fields: message, address, first_name, last_name, email, topic, send_to
Response: { address, representatives[{ name, chamber, phone, captcha }], captchas_needed, auto_submit }
```

### POST /api/send
```
Form fields: (same as preview) + captcha_tokens (JSON: {"sitekey": "token"})
Response: { address, representatives[{ name, status, error }], warnings }
```

---

## Project Structure

```
civic-bridge/
├── app.py                    # FastAPI web application
├── config.py                 # Configuration (env vars)
├── router.py                 # CLI entry point
├── requirements.txt          # Python dependencies
├── engine/
│   ├── address_validator.py  # Address validation + district lookup
│   ├── yaml_parser.py        # Contact form YAML parser
│   ├── form_submitter.py     # Playwright form submission engine
│   └── captcha_solver.py     # CAPTCHA solving integration
├── templates/
│   └── index.html            # Single-page web application
├── static/
│   ├── style.css             # Design system (navy/red/white/black)
│   └── app.js                # Client-side logic (3-page flow)
├── data/
│   ├── contact-congress/     # Form YAML definitions (789 files)
│   └── congress-legislators/ # Current legislator data
└── scripts/
    └── generate_house_yamls.py  # House YAML generator
```

---

## Design

- **Palette**: Deep navy (`#080d1a`), navy card (`#111d3a`), red accent (`#c41e3a`), white text
- **Typography**: Libre Baskerville (headings), Inter (body)
- **Layout**: 3-page flow — Message + Info → Address + Confirm → Results
- **Theme**: Trustworthy, modern, civic. Subtle star field background.

---

## Data Sources

- [unitedstates/contact-congress](https://github.com/unitedstates/contact-congress) — CC0 form definitions
- [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) — CC0 legislator data
- U.S. Census Bureau Geocoder — public API, no key required

---

## License

MIT
