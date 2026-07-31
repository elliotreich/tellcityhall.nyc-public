# NYC Bridge

NYC Bridge is a nonpartisan civic-engagement tool for New York City residents. A resident writes one message, enters a NYC address, and sees the officials who represent that address.

The current launch target is **City Council digest mode**:

1. The address resolves to one of the 51 Council districts.
2. The resident's Council message is stored in a SQLite queue.
3. The resident confirms their email through a verification link.
4. A scheduled job sends one digest per district to the Council office. The digest contains deterministic counts, topic tallies, and constituent messages. AI prose is optional and quote-anchored; it falls back to quotes and tallies when the AI call is unavailable.
5. Other officials retain the older immediate email/form-fallback behavior while Council digest mode is piloted.

## What is implemented

- FastAPI application with address autocomplete, official preview, submission, and email verification routes.
- Census geocoder plus local Council-district point-in-polygon lookup.
- Complete 51-district Council roster with published office emails.
- SQLite/WAL queue with verified-message filtering and digest lifecycle records.
- HTML and plain-text digest rendering.
- Optional Gemini summarization with fabrication guardrails and deterministic fallback.
- Per-recipient-domain pacing for digest delivery.
- `scripts/send_digests.py` with `--dry-run` and `--district` options.
- 111 automated tests covering the existing lookup/email behavior and digest path.

## Important boundaries

- The app does **not** currently automate CAPTCHA-protected official forms. `engine/form_submitter.py` and `engine/captcha_solver.py` are not part of the Council digest launch path.
- A submission is not considered digest-eligible until the constituent verifies their email.
- The queue stores names, email addresses, addresses, topics, messages, and delivery state until the message is delivered or otherwise handled. Do not describe the app as stateless or as storing nothing.
- Email-provider acceptance is not the same as confirmed inbox delivery. A real provider configuration and a test mailbox are required before launch.

## Local development

Python 3.10+ is required. The repository's virtual environment is the supported runtime:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/uvicorn app:app --reload
```

The current verified test result is **111 passed**.

To render a digest without sending email:

```bash
.venv/bin/python scripts/send_digests.py --dry-run --district 1
```

## Configuration

Set these through the deployment environment or a secrets manager:

- `FROM_EMAIL`, `FROM_NAME`
- `SENDGRID_API_KEY` or `MAILGUN_API_KEY` + `MAILGUN_DOMAIN`, or SMTP settings
- `DIGEST_VERIFY_BASE_URL` — public HTTPS base URL used in verification links
- `NYC_BRIDGE_GEMINI_KEY` — optional dedicated Gemini key; empty means deterministic fallback
- `DIGEST_MIN_FOR_SUMMARY` — defaults to `12`
- `DIGEST_DOMAIN_DELAY` — defaults to `2` seconds
- `DIGEST_DB_PATH` is currently a code-level path and defaults to `data/queue.db`; the deployment must put it on persistent storage.

## Launch blockers

Before making this public, finish and verify:

1. Choose a persistent runtime. The current SQLite queue is suitable for a single persistent VPS, not an ephemeral container without a database migration.
2. Configure a dedicated sending identity/provider and verify a real outbound message to a controlled test mailbox.
3. Set `DIGEST_VERIFY_BASE_URL` to the final HTTPS domain and test the complete submit → verify → dry-run digest flow.
4. Add a supervised weekday scheduler for `scripts/send_digests.py`, with logs and an alert on failed runs.
5. Add abuse protection, privacy/retention language, and an operator runbook before inviting public traffic.
6. Independently verify the Council roster and district data immediately before launch.

The standing infrastructure direction is Cloudflare for public DNS/TLS and the existing Oracle VPS for this stateful Python/SQLite service, unless the queue is migrated to a managed database first.
