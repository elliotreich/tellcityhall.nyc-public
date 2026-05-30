# Closing the Gap: Proof-of-Concept → Production

> **Grounded assessment.** Every claim below was verified against the code at
> the merged commit (`6c321cb`), not from memory. The test suite was run
> (**50 passed**), the officials data was audited programmatically, and the
> send paths in `app.py` and `router.py` were traced line by line. Where the
> earlier draft of this document was wrong, it's corrected and flagged.

---

## The single most important correction

**Delivery is email-only today. Web-form automation is not wired in.**

`engine/form_submitter.py` (Playwright) exists, and all the form YAML
definitions exist with real steps — but `submit_message` / `FormSubmitter`
is referenced **nowhere** in `app.py` or `router.py`. Both send paths import
only `engine/email_sender.py`. The form-delivery branch in `app.py` is
explicit about it:

```python
elif official.contact_method == "form" and official.form_key:
    # Form-based delivery — attempt Playwright submission
    # For now, fall back to email if email is available, or mark as needs_manual
```

So every official is reached **by email or not at all.**

### What that means per official (with SMTP configured)

| Outcome | Count | Who |
|---|---|---|
| **Delivered by email** | up to 5 | NYS Comptroller; Manhattan BP, Queens BP; the 5 DAs; your Council member (51/51 have email); your State Senator & Assembly Member (all rostered entries have email) |
| **Form official, email fallback works** | 2 | Public Advocate, NYC Comptroller |
| **Form official, NO email → `manual_redirect` (not delivered)** | **6** | **Mayor, Governor, Attorney General, Bronx BP, Brooklyn BP, Staten Island BP** |

The earlier draft claimed "4 form-only officials (Mayor, Brooklyn BP, Governor,
AG)." The data shows **6** — it missed Bronx BP and Staten Island BP. Manhattan
and Queens BPs *do* have email, so they deliver fine; the other three boroughs'
BPs do not.

**And without SMTP credentials, nothing is delivered at all** — there is no
local-spool or dry-run delivery, so the working demo is "compose + preview,"
not "send."

---

## Gap 1: Web-form automation is unwired (the biggest functional gap)

**Verified state:** 6 officials have no email and currently get a
`manual_redirect` (web) / "No delivery method available" (CLI). Their form
YAMLs are real and non-trivial — step counts: `nyc_mayor` 15, `nys_governor`
14, `nys_ag` 14, `nyc_bronx_bp` 10, `nyc_staten_island_bp` 13,
`nyc_brooklyn_bp` 4 (Microsoft Forms, minimal). They're just never executed.

**What needs to happen:**

1. **Wire `form_submitter` into both send paths.** In `app.py` and
   `router.py`, the `contact_method == "form"` branch should call
   `submit_message(form_key, context)` and translate `SubmissionResult` into
   the delivery-result dict, instead of jumping straight to the email/redirect
   fallback. The Playwright engine and YAML parser already exist; this is
   integration, not new infrastructure.
2. **Keep email fallback as the second tier, redirect as the third.** Order:
   form submit → (on failure) email if present → (else) manual redirect with
   the official's URL. The current redirect tier stays as the floor.
3. **Triage the 6 forms by platform** (these are genuinely different in
   difficulty):
   - **NYS AG (Drupal webform):** standardized — most likely to "just work."
     Test first.
   - **Mayor (nyc.gov) / Governor (AEM):** need a real headed-browser run to
     confirm whether they block automation or merely tripped the earlier audit
     tool. Unknown until tested.
   - **Bronx / Staten Island BP:** test the drafted steps against the live
     forms.
   - **Brooklyn BP (Microsoft Forms):** MS Forms actively resists automation.
     Realistic outcome is to find a constituent-services email instead, or keep
     it as an honest manual redirect.
4. **CAPTCHA path:** `engine/captcha_solver.py` supports 2captcha/anti-captcha
   but is untested against any live NYC form. Validate against whichever of the
   6 actually present a CAPTCHA.

**Estimated work:** 4–6 days, and inherently uncertain — some of these may not
be automatable at all (see "hard gaps").

---

## Gap 2: Address resolution has a single point of failure

**Verified state:** `validate_and_resolve` uses the **US Census Geocoder
only** — there is no second geocoder. `_parse_address_components` is
comma-splitting + regex. There is no Geoclient/PLUTO fallback anywhere in the
code (config has no Geoclient key; only Census + an unused Google Civic key
inherited from the federal codebase).

**Real impact:** Census has documented NYC blind spots (some municipal
buildings, PO boxes, certain hyphenated Queens addresses). A miss = a flat
"Address not found," and the user is done.

**What needs to happen:**

1. **Add an NYC-native fallback geocoder** — NYC Planning's GeoSearch
   (`geosearch.planninglabs.nyc`, free, no key) or the Geoclient API (free with
   an NYC developer account). Chain: Census → GeoSearch → helpful error.
2. **Normalize before querying** — expand `St`→`Street`, handle `Centre`/
   `Center`, strip apartment/unit, retry without unit on zero matches.
3. **Measure it.** Run a representative sample (≥1,000 addresses across all 5
   boroughs / many ZIPs) from NYC Open Data Address Points through the resolver
   and report the real failure rate. Target <2%. *(The earlier doc cited "11/17
   passed" — treat that as anecdotal; this is the test that actually answers
   "works for any NYC address.")*

**Estimated work:** 3–4 days.

---

## Gap 3: Districts can be silently mis-resolved or dropped

Two distinct defects here, both verified in code:

**3a. State-roster gaps cause silent drops.** `data/nyc_officials.yaml` has
**27 state-senate** entries (districts 10–59) and **43 state-assembly** entries
(districts 34–87). When the Census layer returns a district number that isn't
in the roster, `get_state_senator` / `get_state_assembly_member` return `None`
and the official is dropped from the list **with no warning** — the user is
told they contacted "everyone" while a representative is missing. The roster
must be audited for completeness against the authoritative NYC district list,
and a "district resolved but official not found" case must surface a visible
notice instead of disappearing.

**3b. Council point-in-polygon always returns *something*.**
`_point_in_council_district` falls back to "nearest district centroid" when no
polygon contains the point, so it can return `0` only if the GeoJSON is empty.
That means a slightly-off coordinate near a border can be confidently assigned
to the **wrong** district rather than flagged as uncertain. Boundary-precision
testing (an address near each of the 51 district edges) is needed, and the
nearest-centroid fallback should be distance-bounded (reject if the nearest
centroid is implausibly far).

**Estimated work:** 2–3 days (roster audit + boundary tests + warning paths).

---

## Gap 4: Email deliverability is untested against real .gov inboxes

**Verified state:** `email_sender.py` supports SendGrid, Mailgun, and direct
SMTP (`aiosmtplib`) with a basic rate limiter, and 50 unit tests confirm it
*composes* mail correctly. It has never been run with real credentials — there
are no secrets configured, and "success" currently means "SMTP/API accepted,"
not "landed in the inbox."

**What needs to happen:**

1. Provision real credentials (SendGrid free tier is enough to start); set up
   **SPF + DKIM + DMARC** on the sending domain.
2. Inbox-placement testing (Mail-Tester/GlockApps) against Gmail/Outlook and,
   if possible, a `.gov` recipient. `.gov` filters are aggressive.
3. **Bounce handling** — a `250` is not a delivery. Process provider bounce
   webhooks and downgrade those results from "sent" to "delivery failed."
4. **Per-domain rate limiting** — sending up to 11 messages at once can trip
   per-recipient-domain throttles on `nyc.gov` / `nysenate.gov`. The current
   limiter is global, not per-domain.

**Estimated work:** 2 days.

---

## Gap 5: No fallbacks for external dependencies

**Verified state:** the GeoJSON is cached at startup (good). But the Census
call has no retry, and a Census outage = total failure ("Address lookup
service unavailable"). The send loop *does* already continue past a single
official's failure (verified — each official is handled in its own try/except),
so partial-failure degradation is in place.

**What needs to happen:** retry-with-backoff on the Census call; the geocoder
fallback chain from Gap 2; a circuit-breaker that skips a form endpoint
returning 5xx instead of waiting on a timeout.

**Estimated work:** 1–2 days.

---

## Gap 6: Abuse prevention

**Verified state:** the `/api/send` endpoint has no per-IP/per-session rate
limit and no CAPTCHA. The only throttle is the email sender's internal limiter.
Anyone could script the endpoint to mass-message an official, which is the
fastest way to get the sending domain blocked by `*.gov` mail.

**What needs to happen:** per-IP/session send cap (e.g. 5/hour, in-memory);
a lightweight Turnstile/hCaptcha on the send flow; a clear ToS (messages are
delivered as-is to government officials; harassment is a crime); a monitored
`abuse@` contact. The constituent's real name + address + email in the body
helps establish legitimacy.

**Estimated work:** 1–2 days.

---

## Gap 7: Official-data freshness

**Verified state:** the data is a static YAML snapshot with no `last_verified`
timestamps and no refresh mechanism. Council emails, vacant seats, and post-
election redistricting will drift with no signal.

**What needs to happen:** add `last_verified` per entry + a staleness warning;
scrape the NYC Council / NYS Senate / NYS Assembly directories to verify
against authoritative sources; explicit vacant-seat handling in the UI;
a scheduled refresh after elections.

**Estimated work:** 2–3 days.

---

## Gap 8: Testing depth

**Verified state:** **50 tests pass** — but they're unit-level
(`test_address_resolver`, `test_email_sender`, `test_officials`). No live
network/integration tests, no district-boundary tests, no concurrency/load
tests, no malformed-input fuzzing.

**What needs to happen:** the 1,000-address corpus run (Gap 2); a boundary test
per council district (Gap 3b); fuzz the address parser (Unicode, huge strings,
empty bodies); concurrency test on `/api/send`.

**Estimated work:** 2–3 days.

---

## Gap 9: Deployment & operations

**Verified state:** no Dockerfile, no structured logging, no health endpoint,
no monitoring, no deploy config.

**What needs to happen:** Dockerfile (Python + Playwright browsers once forms
are wired); deploy to a small VPS / Fly.io with secrets via env; JSON logs with
a request ID and per-send audit line (official, method, status, duration) — this
is the record for when an office says "we never got it"; `/api/health` checking
Census + SMTP + GeoJSON; uptime monitoring; domain + HTTPS.

**Estimated work:** 1–2 days.

---

## Gap 10: Accessibility & UX

**Verified state:** the UI works and has an `#sr-announcer` aria-live region,
but no verified screen-reader/keyboard testing, focus isn't moved on page
transitions, error messages are terse ("Address not found"), and there's no
progress indicator during a send that can take 30+ seconds.

**What needs to happen:** verify aria-live announcements; move focus on
transitions; full keyboard pass with visible focus; actionable error copy;
per-official progress feedback during send.

**Estimated work:** 2–3 days.

---

## The hard gaps (cannot be fully closed — manage, don't "fix")

1. **Form drift.** Offices redesign sites; YAML selectors break and messages
   fail silently. Mitigation: a daily health check that submits a canary to each
   form, plus email fallback wherever an address exists.
2. **MS Forms / AEM / proprietary platforms.** Brooklyn BP (MS Forms) and the
   Governor (AEM) may simply not be automatable. Answer: find an alternate
   channel (constituent-services email / phone) or keep an honest manual
   redirect and say why.
3. **Staff-side filtering.** Offices may filter mass mail. Personalized
   content + real constituent identity in the body is the only lever we have.
4. **Constitutional officers don't do constituent services.** The Mayor and
   Governor don't fix potholes; the tool should be honest about each official's
   role.

---

## Phased roadmap

### Phase A — Make it actually deliver (≈1.5 weeks)
Gaps 1 (wire forms), 2 (geocoder fallback), 3 (silent-drop + boundary), 5
(resilience).
- Result: a valid NYC address resolves correctly, no official silently
  vanishes, and all 11 are *attempted* via a real channel — not 7 by email and
  4 redirected.

### Phase B — Make it trustworthy (≈1 week)
Gaps 4 (real SMTP + bounce handling), 6 (abuse controls), 7 (data freshness).
- Result: messages actually land, the domain doesn't get blocked, data isn't
  stale.

### Phase C — Make it operable (≈3–4 days)
Gaps 8 (corpus + load + fuzz), 9 (Docker/deploy/logging/health), 10 (a11y/UX).
- Result: ready for public traffic with an audit trail.

**Total: ~3 weeks** to "works for any NYC address, attempts all 11 officials
through a real channel, won't break or get blocked." The schedule risk lives
almost entirely in Gap 1 — if two or three of the six forms turn out to be
un-automatable, those officials stay on email/redirect and that's a product
decision, not a bug.

---

## What to tell stakeholders (honest version)

- **What exists today:** a tested core (50 passing tests) that resolves an NYC
  address to up to 11 officials and **delivers by email**. With SMTP keys, ~7
  of 11 are reachable now; 6 form-only officials (incl. Mayor, Governor, AG)
  are not yet delivered — they're shown as "contact via website." Form
  automation is built but not yet connected.
- **What it is:** a working proof-of-concept and a sound architecture — not yet
  a send-to-everyone-with-one-click product.
- **What it needs:** ~3 weeks, concentrated on connecting form automation and
  hardening address resolution. Email delivery is one SMTP key away from live.
- **Who should run it:** ideally the city or a nonpartisan civic group — the
  tool is neutral by construction (it contacts every official regardless of
  party).
