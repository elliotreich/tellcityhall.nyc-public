# NYC Bridge — case study (production source remains private)

**Live product:** [tellcityhall.nyc](https://tellcityhall.nyc)
**Private source:** `tellcityhall.nyc` (Python, 131k Python) — not public. This repo is the public legibility layer.

NYC Bridge is a nonpartisan civic engagement tool that lets New Yorkers write a message once and have it delivered to their City Council member, Borough President, and other local elected officials — 11 offices — through each representative’s official contact form.

> Your voice, delivered to City Hall.

## How it works

1. **Write** your message
2. **Locate** your 11 officials (Council + Borough President + city/state)
3. **Deliver** via official forms — no scraping, no pretending to be you

The full product scope remains in the private source repository.

## Architecture (excerpt)

```
app.py / router.py / engine/ — routing to 11 official forms
templates/ — UI
tests/ — pytest
```

City/state routing is distinct from the federal Civic Bridge (`myposition.us`) — this is NYC-specific.

## How to verify

Live product at https://tellcityhall.nyc — enter a NYC address and see the 11 officials resolved.

## Tests & Maintenance

```bash
# In private checkout
pytest -q
python app.py
```

## Source boundaries

Private `tellcityhall.nyc` remains private (live form-fill). This docs repo is MIT and is the portfolio proof.

## License

MIT

## Links

- Private: `tellcityhall.nyc` (Python 131k, pushed 2026-08-16)
- Live: https://tellcityhall.nyc
