# NYC Bridge — Digest Mode Handoff

**Written 2026-07-27. Every factual claim below was verified against the running code, not recalled.**
Goal: take NYC Bridge from "working lookup engine" to "launchable product that emails NYC City Council offices a daily digest of constituent messages."

---

## 0. READ THIS FIRST — three docs in the repo are wrong

- **`README.md` is inaccurate and must NOT go public.** It claims 59 officials / "100%" coverage, a working Playwright + inline-CAPTCHA form pipeline, and a `nyc-bridge.service` systemd unit on the VPS. **All three are false.** No form automation is wired in, and no such systemd service exists (only `civic-bridge.service`, a *different* app, is running).
- **`CLOSING_THE_GAP.md` is accurate — trust it over the README.** It was written by tracing the code line by line, and it self-corrects the earlier draft. Its "What to tell stakeholders (honest version)" section at the bottom is the truthful description of this project.
- **But `CLOSING_THE_GAP.md`'s roadmap is now partly obsolete.** See §3 — the digest decision deletes its single largest work item.

---

## 1. Where the code is

> ### ⛔ START HERE — read before running anything
> **All digest work is on the `digest-mode` branch, pushed to GitHub.** `main` is stale
> (`f37cbc1`) and does NOT contain it. Clone and check out `digest-mode`:
> ```bash
> git clone -b digest-mode https://github.com/elliotreich/nyc-bridge.git
> ```
> **Do NOT work from any directory named `nyc-bridge.broken-*`** — that is a backup of a
> corrupted repo with no `.git` and no digest code. On 2026-07-27 a Codex session found it,
> assumed the digest work didn't exist, and planned to build the out-of-scope Playwright
> work. The Mac copy has been deleted; one remains on the VPS as a rollback.
> **Also do not confuse this with `your-nyc` / `myfree.nyc`** — a different, live project
> with its own `HANDOFF.md`.

| | |
|---|---|
| **Repo** | `github.com/elliotreich/nyc-bridge` (private) |
| **Branch — all digest work** | **`digest-mode`** @ `5be64bd` (on GitHub) |
| **`main`** | `f37cbc1` — stale, pre-digest. Do not start here. |
| **Mac clone** | `~/syncthing-shared/dev/nyc-bridge` |
| **VPS clone** | `elliot@burningbush:~/Projects/dev/nyc-bridge` (`ssh vps`) |
| **Tests** | **110/110 pass.** Verified 2026-07-27 |
| **Stack** | Python 3.11, FastAPI, uvicorn, stdlib `sqlite3`, `aiosmtplib`, shapely, jinja2 |

**If the VPS is unreachable** (Tailscale down, no DNS), just clone from GitHub and work
locally — nothing in Stage 1 requires the VPS. Note `requirements.txt` pins `playwright`,
which is heavy and **not needed for digest work**; if install fails, install everything
except playwright.

### Git note (already fixed — don't re-diagnose)
The VPS repo previously reported `bad object HEAD` / invalid sha1 `f37cbc1`. **This was not corruption.** The VPS has no GitHub credentials (`gh` not logged in; the only SSH key present is a deploy key scoped to a different repo, `contacts-archive`), so it could never fetch the newest commit. A healthy `.git` was copied from a Mac clone on 2026-07-27; `git fsck` is now silent and `git status` is clean. A backup of the old state is at `~/Projects/dev/nyc-bridge.broken-2026-07-27` — safe to delete once you're confident.

**Still outstanding:** the VPS cannot push. Either run `gh auth login` there, add a key with access to `nyc-bridge`, or push from the Mac (which has full `repo` scope).

**Gotcha:** if you ever copy files from the Mac, strip AppleDouble `._*` files — they break git ("index file ... is too small"). `find .git -name '._*' -delete`.

---

## 2. What actually works today (verified, not assumed)

- Address → Council district resolution via **US Census geocoder** + local `nyc_council_districts.geojson` point-in-polygon.
- **All 51 Council districts have an email**, all on the single domain `council.nyc.gov`, all `contact_method: email`. Verified by parsing `data/nyc_officials.yaml` (key `council`, a **dict keyed by district number 1–51**, not a list).
- Email **composition** (`engine/email_sender.py`, supports SMTP / SendGrid / Mailgun).
- Routes today: `GET /`, `GET /api/autocomplete`, `POST /api/preview`, `POST /api/send`.

### What does NOT work — the two things that matter most
1. **Digest mode does not exist in any form.** The app is stateless and sends immediately, one email per constituent per official. Everything in §4 is net-new code.
2. **This app has never sent a real email.** All 50 tests mock the transport. "Success" currently means "SMTP/API accepted," which is *not* delivery. There are no working credentials configured.

---

## 3. The product decision (made 2026-07-27) — and what it deletes

**Digest design (Elliot's):** rather than flooding offices with individual emails, messages are queued per Council district and delivered as **one digest email per office per cycle**. Page 1 is a cover letter with top-line takeaways and the policy matters raised; subsequent pages carry the raw constituent messages. Delivered at a time that suits a chief of staff.

**Scope decisions:**
- **v1 is City Council ONLY (51 offices).** This is the only group where every official is reachable by email, on one domain. All other officials keep the existing immediate-send behavior.
- **Cover page is "moderate / quote-anchored"** (see §4.2 — this is the highest-risk component).
- **Cadence: weekdays only.** Better product (no Sunday sends) and lower volume.

### ⚠️ This deletes Gap 1 from CLOSING_THE_GAP.md — do not build it
`CLOSING_THE_GAP.md` Gap 1 is "wire the Playwright `form_submitter`" (4–6 days; the doc says "the schedule risk lives almost entirely in Gap 1"). It exists to reach 6 form-only officials (Mayor, Governor, AG, Bronx/Brooklyn/SI BP). **You cannot deliver a multi-page digest through a web contact form.** Council-only v1 means all 51 targets are email.

**Therefore: do not touch `engine/form_submitter.py`, `engine/captcha_solver.py`, or any Playwright/CAPTCHA code. It is out of scope for launch.**

### Volume math (drives the email tier)
One office gets at most one digest per cycle, so volume is decoupled from user traffic:
- Daily: 51 × 31 = **1,581/mo** (absolute ceiling)
- **Weekdays: 51 × 22 = 1,122/mo** ← chosen
- Weekly: 51 × 4.33 = ~221/mo

**Resend Free = 3,000/mo but 100/day.** The monthly cap is comfortable; **the 100/day cap is the binding constraint** — 51 digests in a burst leaves only ~49 for constituent verification emails that day. Rate-limit verification sends accordingly. (Postmark's free tier is 100/**month** — unusable here; it only starts at $15/mo.)

---

## 4. What to build (Stage 1 = the testable milestone)

> ### ⚠️ STATUS UPDATE — Stage 1 is ALREADY LARGELY BUILT, UNREVIEWED
> On 2026-07-27 ~16:00–16:05 UTC a free build agent ran against `DIGEST_SPEC.md` and produced,
> **uncommitted, on the `digest-mode` branch**: `engine/queue.py` (266 lines),
> `engine/digest_builder.py` (344), `scripts/send_digests.py` (242),
> `tests/test_queue.py`, `tests/test_digest_builder.py`, `tests/test_rate_limit.py`,
> plus edits to `app.py`, `config.py`, `engine/email_sender.py`, `.gitignore`.
>
> **Verified by hand:** the suite is **95 passed** (was 50; all original 50 still pass).
> A digest renders correctly end-to-end (cover page → tallies → quotes → raw messages),
> and the `<3` low-volume rule correctly suppresses the cover page for a single message.
>
> **UPDATE — Stage 1 is now committed and the LLM is wired.**
> - Commit `59d0bcc` — digest mode (queue, builder, scheduler, tests).
> - Commit `3280815` — Gemini summarizer + fabrication guardrails, threshold 3 → 12.
> - **110 tests pass** (50 original + digest + 15 new guardrail tests).
> - `data/queue-state.json` was empty scaffolding — harmless.
>
> **Remaining caveats:**
> - **Still not human-reviewed.** The digest/queue/scheduler code was machine-written
>   and its tests were written by the same agent. The *guardrail* tests
>   (`tests/test_guardrails.py`) were written separately and adversarially, and were
>   verified to reject 9 real fabrication patterns while accepting a faithful summary.
> - **The Gemini path has never run against the live API** — `NYC_BRIDGE_GEMINI_KEY`
>   is still a placeholder in Infisical (see §6). Everything to date exercises the
>   deterministic path and mocked failures. First real call is untested.
> - `build_digest_text(district, council_member_name, messages, ...)` — the parameter
>   is `council_member_name`, not `official_name`.
>
> Treat the rest of §4 as the **spec to review the existing code against**, not a from-scratch build order.

Full spec lives at **`DIGEST_SPEC.md` in the repo root** on the `digest-mode` branch. Summary:

### 4.1 Persistence — `engine/queue.py`
SQLite at `data/queue.db`, WAL mode, stdlib `sqlite3`, no ORM.
- `pending_messages`: `id, district, sender_name, sender_email, sender_address, topic, message, submitted_at, status (pending|sent|failed), digest_id, verified`
- `digests`: `id, district, sent_at, message_count, status`
- Functions: `enqueue(...)`, `pending_for_district(d)`, `mark_sent(ids, digest_id)`

**Note:** the README currently promises "Nothing is stored." Digest mode makes that false. The privacy copy must be rewritten to describe real retention.

### 4.2 Cover page — `engine/digest_builder.py` ⚠️ HIGHEST RISK
- **Deterministic in code, never AI:** total counts, per-topic tallies, date range.
- **AI:** a short 2–3 sentence prose summary per topic.
- **HARD RULE: every claim in AI prose must trace to a real submitted message, and each topic summary must carry at least one verbatim quoted excerpt.** Never invent, infer, or extrapolate a constituent position. If a topic is too thin or vague, emit quotes only with **no** prose.
- **Must have a deterministic fallback** (quotes + tallies, no LLM) that is used automatically if no LLM is configured, the call fails, or it returns empty.
- Render HTML (cover page, then messages) + a plain-text alternative.

*Why this is flagged:* an AI-fabricated constituent position, sent to a government office from a civic tool, is the worst possible failure for this product's credibility. Constrain it hard.

### 4.3 Low-volume rule
**`DIGEST_MIN_FOR_SUMMARY = 12`** (raised from 3 by Elliot on 2026-07-27). Below 12 pending messages, forward them plainly with **no cover letter** — a cover page "summarising" a handful of messages a staffer could read directly is noise, and makes the tool look like it is performing analysis rather than doing it. **0 pending → send nothing.**

Consequence worth knowing: early on, most districts will fall below 12, so most digests ship with **no AI at all**. That is intended — the risky component only activates when there is enough material to summarise meaningfully.

### 4.3b AI summarisation — implemented (commit `3280815`)
`LLMSummarizer` calls Gemini directly (stdlib `urllib`, no SDK) using
`NYC_BRIDGE_GEMINI_KEY` / `DIGEST_GEMINI_MODEL` (default `gemini-flash-lite-latest`).

**The guardrail design — do not weaken this:**
- **Quotes and tallies are always deterministic**, extracted in code from real messages. The model *only* supplies prose, so it can never invent a quote.
- `_verify_prose()` rejects prose that: exceeds 600 chars; matches banned patterns (percentages, "majority of", "all/every constituent", "polls/studies show", "demands that you"); or is lexically ungrounded (>50% of content words absent from the source messages).
- A topic whose prose fails verification **degrades to quotes-only** rather than shipping unverified text.
- No key / API failure / empty response → deterministic fallback.
- The prompt itself forbids outside facts, counts, generalisation, and recommendations, and instructs the model to reply `INSUFFICIENT` rather than strain.

Verified adversarially: 9 fabrication patterns rejected (invented statistic, false generalisation, majority claim, cited research, every-resident claim, polling claim, ungrounded topic drift, over-generation, sentinel) while a faithful grounded summary is accepted. See `tests/test_guardrails.py`.

### 4.4 Reply-To routing
A chief of staff **must** be able to reply to the actual constituent. One constituent → `Reply-To` = their address. Several → `Reply-To` = sender, with each constituent's email shown clearly beside their message. Without this the digest reads as astroturf and the product's value collapses.

### 4.5 Per-recipient-domain rate limiting
All 51 digests hit `council.nyc.gov` in one burst. The limiter in `engine/email_sender.py` (`_rate_limit`, line ~42) is currently **global**; make it **per-recipient-domain**. Default: max 1 message / 2s per domain.

### 4.6 Constituent email verification
Token via `secrets.token_urlsafe`, a `verified` flag, endpoint `GET /verify/{token}`. **Unverified messages are never included in a digest.** This is what stops one bad actor from getting the sending domain blocked.

### 4.7 Scheduler — `scripts/send_digests.py`
Iterate all 51 districts, build + send due digests, log results. **Idempotent** — never send a queued message twice. Support `--dry-run` (render without sending) and `--district N`. Do **not** install cron/systemd yet.

### 4.8 Tests
Add `tests/test_queue.py`, `tests/test_digest_builder.py`, `tests/test_rate_limit.py`. Cover: enqueue/dequeue, idempotency, the `<3` rule, unverified exclusion, per-domain limiting, and that the deterministic fallback builds a valid digest with no LLM. **The existing 50 tests must still pass.**

---

## 5. Staging — Stage 1 needs nothing external

**Stage 1 (~2–3 days) — a product Elliot can actually test. → MOSTLY BUILT, needs review (see §4 status box).**
§4.1–4.3 + `--dry-run`. Ends with: submit test messages, read a real rendered digest. **No domain, no Resend account, no credentials, no spending required.** This is the "see it working" milestone. Remaining work is **review + commit + wire the LLM summarizer with its guardrails**, not a from-scratch build.

**Stage 2 (~2 days) — real delivery. Needs the new domain + Resend account.**
§4.4–4.6, plus SPF/DKIM/DMARC on the new domain. Ends with a real digest in a real inbox — **Elliot's own, not an office's.**

**Stage 3 (~2 days) — safe to point at government.**
Honest README rewrite (§0), abuse controls, scheduler enrollment, and a deliberate **domain warm-up** before any `.gov` traffic.

---

## 6. Identity & infrastructure constraints (non-negotiable)

- **Digests must NOT send from `elliot@elliotreich.com` or any personal address.** Elliot is buying a **dedicated domain** for the product; all office-facing mail sends from that domain, on a **new, product-owned Resend account**. He is happy to be publicly credited as the builder, but the product must not depend on his personal stack or identity.
- **Cold-domain risk is the top launch hazard.** A brand-new domain sending 51 automated messages into `council.nyc.gov` is textbook spam-filter bait, and `.gov` filters are unforgiving. SPF + DKIM + DMARC are launch-blocking, not polish. Warm up by sending to Elliot's own inboxes for several days before any office receives anything.
- **Hosting: OPEN — Elliot wants this OFF his personal VPS if possible.** Decision deferred until the code works (it is host-agnostic Python). Analysis:
  - **Google Cloud Run + Firestore — the leading option.** Deploys the existing Python/FastAPI app **with no rewrite**; 2M requests/month always-free. Digest mode is a **once-daily batch job** (Cloud Scheduler → wake → process all districts → sleep), so cold start is irrelevant and compute is billed only for the ~30s it runs. **Cost: SQLite will not survive** — Cloud Run containers are ephemeral and messages arrive while scaled to zero, so `data/queue.db` must be ported to **Firestore** (free tier). That port is the main migration work. Requires a GCP billing account on file (will not charge at this volume).
  - **Cloudflare Workers + D1 — rejected for now.** Workers are JS/TS; this is Python. Would mean rewriting ~1,900 lines of tested code. Cost is a rewrite, not money.
  - **Oracle VPS — the fallback.** Zero migration; SQLite + cron work as built today. But it keeps the product on Elliot's personal infrastructure, which he explicitly wants to avoid. **Oracle hard limit: $0.00, Always Free only.**
  - Either way, **Cloudflare** handles DNS/TLS/email auth on the new domain.
  - **Design for resumability:** if the daily run dies mid-way through district 30, it must not re-send districts 1–29. The per-message idempotency already built is the right foundation — preserve it through any storage port.
- **Do not `git push` from the VPS** until its GitHub auth is fixed (§1).
- **Do not buy the domain** — Elliot purchases it himself.

### Inference key — dedicated, already provisioned
Digest summarisation runs on **one dedicated Google AI Studio key**, isolated from all other inference:
- Infisical secret name: **`NYC_BRIDGE_GEMINI_KEY`** — created 2026-07-27, currently a **PLACEHOLDER**. Elliot generates the real key in a **dedicated AI Studio project** and replaces the value.
- **It must live in its own AI Studio project**: Gemini free-tier quota is enforced **per Google Cloud project, not per key**. A key inside an existing project shares that project's limits.
- **`GEMINI_8` was removed from the LiteLLM router** (config `~/Projects/infrastructure/litellm/config.yaml`, backup `config.yaml.bak-pre-nycbridge-20260727`) so this lane can never be consumed by general agent traffic. Its 4 deployments were all in the generic `free` pool; the pool went 8 → 7 keys with no lane disabled. Router restarted and verified: `/health/liveliness` OK and a live `free` completion returned normally.
- The old `GEMINI_8` secret value is still in Infisical as a rollback. Remove it once the new key is confirmed working.

---

## 7. Known real defects (from CLOSING_THE_GAP.md, still valid)

These are **not** blockers for Stage 1, but they are real and should not be forgotten:
- **Single-geocoder SPOF.** Census only, no fallback; a Census outage or a known NYC blind spot (some hyphenated Queens addresses, PO boxes) = flat failure. Fix: chain Census → NYC Planning GeoSearch (`geosearch.planninglabs.nyc`, free, no key).
- **Silent district drops.** `data/nyc_officials.yaml` has incomplete **state** rosters (27 senate, 43 assembly entries); a missing district returns `None` and the official vanishes **with no warning**. *(Council is complete at 51/51, so this does not affect Council-only v1.)*
- **Council point-in-polygon always returns something.** `_point_in_council_district` falls back to nearest-centroid, so a borderline coordinate can be confidently assigned to the **wrong** district instead of flagged. Should be distance-bounded.
- No retry/backoff on the Census call.

---

## 8. Context Codex will otherwise get wrong

- **The BetaNYC story.** Elliot's 2026-06-03 outreach went to `andrew@beta.nyc` **and** `noel@beta.nyc`. **Only one bounce exists — for Noel.** Andrew most likely received it and simply didn't reply. The bounce was a misconfigured Gmail "send-as" through `smtp.resend.com` (`550 idempotency key`) on Elliot's *personal* pipe — which is now irrelevant to the product, since the product gets its own domain and account. **Do not describe this as "BetaNYC never received it."**
- **The BetaNYC meeting was never a true blocker.** It was going to answer one design question — individual sends vs. digest. Elliot has now answered it himself, and the answer is well-supported (51/51 Council offices, one email domain). Skipping the consult costs external validation, not capability. Do not treat it as an outstanding dependency.
- **`nyc.elliotreich.com` is a DIFFERENT project** (now live as `myfree.nyc`). It has nothing to do with NYC Bridge. NYC Bridge has never had a website.
- **A prior Codex session (2026-07-27) failed without changing anything.** Recorded so it isn't repeated: it ran on the **Mac**, where `~/Projects` does not exist, so it never found the repo or this handoff; the Mac had **no working DNS** (`cannot resolve pypi.org`, `tailscale status` → "Failed to load preferences"), so it could neither install dependencies nor reach the VPS; it then worked from `nyc-bridge.broken-2026-07-27`, concluded the digest work didn't exist, and drafted a plan to build the **out-of-scope Playwright automation** before hitting rate limits. It read `your-nyc/HANDOFF.md` (a different project) rather than this file. **Nothing it produced should be acted on.** The repo was verified untouched afterward: 3 commits intact, clean tree, 110 tests passing. Mitigations since: `digest-mode` pushed to GitHub, a Mac clone created, and the misleading backup directory deleted from the Mac.
- **`civic-bridge` and `nyc-bridge` are separate repos and must not be merged.** Civic Bridge is the *federal* app (Congress) and is live at `congress.elliotreich.com` via `civic-bridge.service` on port 8081. They were painfully untangled on 2026-05-30.

---

## 9. First command

```bash
git clone -b digest-mode https://github.com/elliotreich/nyc-bridge.git
cd nyc-bridge && git log --oneline -3   # -> 5be64bd, 3280815, 59d0bcc
python3 -m venv .venv                   # MUST be Python 3.10+, NOT macOS system 3.9
.venv/bin/pip install pyyaml httpx aiosmtplib shapely fastapi uvicorn jinja2 pytest pytest-asyncio
.venv/bin/python -m pytest tests/ -q    # -> 110 passed
cat DIGEST_SPEC.md HANDOFF.md
```

**Two install gotchas, both verified 2026-07-27:**
- **Python 3.10+ is required.** On macOS system Python 3.9, 12 tests fail with
  `RuntimeError: There is no current event loop` — 3.9 cannot construct
  `asyncio.Semaphore()` outside a running loop. The code is fine; 3.9 is too old.
  Verified 110/110 on 3.14 and on the VPS's 3.10.
- **Skip `playwright`.** It is in `requirements.txt` for the out-of-scope form
  automation, is a heavy install, and digest work does not import it. Install the
  packages listed above instead of `-r requirements.txt`.

Render a digest yourself before changing anything:
```bash
./.venv/bin/python -c "
from engine.digest_builder import build_digest_text
m=[dict(sender_name='Ana R',sender_email='ana@x.com',topic='Housing',message='Rent increases are pushing me out.',submitted_at='2026-07-25'),
   dict(sender_name='Ben K',sender_email='ben@x.com',topic='Housing',message='Landlord ignored three heat complaints.',submitted_at='2026-07-26'),
   dict(sender_name='Cy L',sender_email='cy@x.com',topic='Transit',message='The M14 is unusable at rush hour.',submitted_at='2026-07-26')]
print(build_digest_text(district=1, council_member_name='Christopher Marte', messages=m))"
```

**Then, in order:**
1. **Review** the machine-written Stage 1 code (`engine/queue.py`, `engine/digest_builder.py`, `scripts/send_digests.py`) against §4. It is committed but not human-reviewed.
2. **Replace the placeholder** `NYC_BRIDGE_GEMINI_KEY` in Infisical with the real AI Studio key (§6), then make the **first live Gemini call** — that path has never run against the real API. Confirm real model output still passes `_verify_prose`; if the guardrail proves too strict on genuine output, tune it **without** removing the fabrication checks.
3. **Decide hosting** (§6) — Cloud Run + Firestore port, or stay on the VPS.
4. **Stage 2** only once the domain + Resend account exist.

Do not start the Playwright/form work (§3). Do not let the README ship as-is (§0).
