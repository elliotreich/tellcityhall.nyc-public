# NYC Bridge — Project Summary

## What It Is

NYC Bridge lets any New York City resident contact **all 11 elected officials** who represent them — city and state — with a single message.

You type your address, write what you want to say, and hit send. Your message goes to your City Council member, Borough President, District Attorney, the Mayor, Public Advocate, Comptroller, your State Senator, your Assembly Member, the Governor, Attorney General, and State Comptroller. All at once.

## Why It Matters

Most people don't know who represents them. They might know the Mayor, maybe their Council member. Almost nobody knows their Assembly district or who their State Senator is. And even if they do, contacting all 11 would mean finding 11 separate contact forms or email addresses, writing 11 separate messages, and spending 30+ minutes on what should take 30 seconds.

The result: only the most motivated people — those with time, education, and know-how — get heard. Everyone else's voice is structurally filtered out.

NYC Bridge removes that filter. One address. One message. Every official.

## How It Works

### Address → District Resolution (single API call)

When a user enters their address, the system hits the Census Bureau's geocoder. It returns four layers of representation from one call:

- **County FIPS code** → maps to borough (Manhattan, Brooklyn, Queens, Bronx, Staten Island)
- **Coordinates** (lat/lon) → point-in-polygon lookup against NYC Council district GeoJSON
- **State Senate district** (from Census geography layers)
- **State Assembly district** (from Census geography layers)

If the address isn't in one of the 5 NYC counties, it's rejected.

### Official Lookup

A YAML database of ~155 officials (the master roster for every position in NYC government) is queried with the resolved districts. It returns exactly 11 officials:

| Category | Officials | Count |
|---|---|---|
| Citywide | Mayor, Public Advocate, Comptroller | 3 |
| District | City Council Member, State Senator, Assembly Member | 3 |
| Borough | Borough President, District Attorney | 2 |
| Statewide | Governor, Attorney General, State Comptroller | 3 |

### Delivery

The system delivers via the best available channel per official:

- **Email officials** (Council members, DAs, State Comptroller): SMTP delivery via SendGrid/Mailgun
- **Form-based officials with email** (Public Advocate, Comptroller, State Senate/Assembly): email fallback using their published email addresses
- **Form-only officials** (Mayor, Governor, Brooklyn BP, AG): these need automated form submission via Playwright (form definitions are written; automation engine exists from a related congressional contact project)

### Architecture

```
Browser (3-page flow: message → address → results)
    ↓
FastAPI (Python)
    ├── Census Geocoder API (address → districts)
    ├── GeoJSON point-in-polygon (council district)
    ├── YAML official database (155 officials)
    ├── Email engine (aiosmtplib + SendGrid/Mailgun)
    └── Playwright form submitter (for form-only officials)
```

- **No database**: nothing is stored. Addresses are used ephemerally for the lookup only.
- **No accounts**: the user never creates a login.
- **Plain-text emails only**: for maximum deliverability and accessibility.

### Privacy

The system was designed to be privacy-respecting by default:
- No address, message, or personal information is persisted
- No user accounts
- No tracking or analytics
- Messages go directly to officials' published contact channels

## Current State (May 2026)

**Working:**
- Address resolution for all 5 boroughs (tested, verified)
- District lookup: council, state senate, state assembly
- Official database: complete roster of ~155 NYC officials with contact methods, emails, phone numbers, party affiliations
- Web UI: 3-page flow with autocomplete, official preview, delivery results
- Email delivery: compose + send to email-based officials (requires SMTP credentials)
- CLI tool: `python router.py "350 Jay St, Brooklyn" --message "..." --first-name "Jane" ...`
- Test suite: 50 tests, all passing

**Needs completion to be production-ready:**
- SMTP credentials (SendGrid API key or equivalent)
- Playwright form automation wired up for 4 form-only officials (form YAML definitions are written)
- Deployment to a public server
- Domain + HTTPS

**Current delivery coverage per resident:**
- With SMTP configured: 7 of 11 officials reached (email + email-fallback)
- With form automation: 11 of 11

## What This Would Take to Launch

This is a small project. The entire codebase is ~3,000 lines across 12 source files. The heavy lifting — address resolution, official data, delivery infrastructure — is done.

To go from current state to public launch:

1. **SMTP credentials** (SendGrid free tier: 100 emails/day) — 5 minutes
2. **Wire up Playwright form automation** for the 4 form-only officials — ~2 days of focused work
3. **Deploy** (anywhere that runs Python — a $6/month VPS, Fly.io, or NYC's own infrastructure)
4. **Domain + HTTPS** — standard setup

Total: under a week of focused work to go from working prototype to public tool.

## Who Might Care About This

### City Council / elected officials
This tool makes constituent contact *easier*, not harder. It doesn't generate spam — the user writes one message, and it goes to the officials who represent them. The message is the same whether they send it through this tool or copy-paste it 11 times. The tool just removes the friction.

### OTI (Office of Technology and Innovation)
This is the kind of civic tech that governments build internally — see [NYC's own website](https://www.nyc.gov) for lookup tools. NYC Bridge does what the city's own infrastructure should: connect residents to their representatives. It could be adopted, hosted on nyc.gov infrastructure, and maintained as a public service.

### Good-government / civic engagement groups
Groups like Citizens Union, Reinvent Albany, or Common Cause NY work on exactly this problem — making government more accessible. This is a concrete, working tool that advances that mission.

### News organizations
The City, Gothamist, or THE CITY could embed this alongside coverage of City Council votes or budget decisions, letting readers act on what they just read.

## Comparison to Existing Tools

| Tool | Finds your reps? | Sends to all of them? | Covers city + state? |
|---|---|---|---|
| NYC Council website | Council member only | No (just shows info) | No |
| NYS Assembly site | Assembly member only | No | No |
| MyReps (NYC) | Council + state leg | No | Yes (info only) |
| Resistbot | Yes (via text) | Yes, but one-at-a-time | Partial |
| **NYC Bridge** | Yes — all 11 | Yes — one click | Yes |

NYC Bridge is unique in doing **one-message-to-all** for the full set of city and state officials who represent a specific address.

## What Success Looks Like

A resident in East New York has a pothole on their block that's been there for 3 weeks. They go to the site, type their address, write "Please fix the pothole at the corner of Pitkin and Euclid," and hit send. Their message reaches their Council member (who handles constituent services), their Borough President (who controls borough-level capital funds), their State Assembly member (who can flag it to DOT), and 8 other officials who now know there's a constituent who cares about street conditions.

The resident spent 60 seconds. They didn't need to know who represents them. They didn't need 11 tabs. They wrote one message and it went everywhere it needed to go.

## Technical Details

- **Backend**: Python 3.14, FastAPI, aiosmtplib, httpx, shapely, PyYAML
- **Frontend**: Single-page vanilla JS (no framework), 3-page flow, CSS custom properties
- **Data**: Census Bureau Geocoder API, NYC Open Data (council districts), master YAML roster
- **Tests**: 50 tests across address resolution, official lookup, and email composition
- **License**: Not yet determined
