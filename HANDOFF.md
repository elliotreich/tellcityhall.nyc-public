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

| | |
|---|---|
| **Repo** | `github.com/elliotreich/nyc-bridge` (private) |
| **VPS path** | `elliot@burningbush:~/Projects/dev/nyc-bridge` (`ssh vps`) |
| **HEAD** | `f37cbc1` — matches GitHub `refs/heads/main` |
| **Branch to work on** | `digest-mode` (already created, checked out on the VPS) |
| **Tests** | **50/50 pass.** Verified 2026-07-27 via `./.venv/bin/python -m pytest tests/ -q` |
| **Stack** | Python 3.11, FastAPI, uvicorn, stdlib `sqlite3`, `aiosmtplib`, shapely, jinja2 |

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
> **Not yet done / caveats — this is the real remaining Stage 1 work:**
> - **NONE of it is code-reviewed by a human, and the tests were written by the same
>   agent that wrote the code.** Review before trusting.
> - **Nothing is committed.** Commit early so work isn't lost.
> - `LLMSummarizer._llm_summarize` **raises `NotImplementedError`** — no LLM is wired
>   in, so it *always* falls back to deterministic quotes+tallies. This is currently
>   safe (it cannot fabricate), but §4.2's quote-anchoring rules are therefore
>   **unenforced and untested against a real model.** Wiring an LLM in is the point at
>   which fabrication risk becomes live — implement the guardrails *with* it.
> - There is a stray `data/queue-state.json` — confirm whether it's real state or debris.
> - `build_digest_text(district, council_member_name, messages, ...)` — note the
>   parameter is `council_member_name`, not `official_name`.
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
`DIGEST_MIN_FOR_SUMMARY = 3`. Below 3 pending messages, forward them plainly — a "digest" summarizing one message is worse than the message. **0 pending → send nothing.** (This is also a natural cost control early on.)

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
- **Hosting:** recommend the **Oracle VPS** (same stack as the already-live `civic-bridge.service`, no rewrite, $0) with **Cloudflare** for DNS/TLS/email auth on the new domain. Per Elliot's stack strategy: new public/edge work → Cloudflare, new **stateful** work → Oracle VPS. Digest mode is stateful. **Oracle hard limit: $0.00, Always Free resources only.**
- **Do not `git push` from the VPS** until its GitHub auth is fixed (§1).
- **Do not buy the domain** — Elliot purchases it himself.

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
- **`civic-bridge` and `nyc-bridge` are separate repos and must not be merged.** Civic Bridge is the *federal* app (Congress) and is live at `congress.elliotreich.com` via `civic-bridge.service` on port 8081. They were painfully untangled on 2026-05-30.

---

## 9. First command

```bash
ssh vps
cd ~/Projects/dev/nyc-bridge && git branch --show-current   # -> digest-mode
git status --short                                           # -> uncommitted Stage 1 work
./.venv/bin/python -m pytest tests/ -q                       # -> 95 passed
cat DIGEST_SPEC.md HANDOFF.md
```

Render a digest yourself before changing anything:
```bash
./.venv/bin/python -c "
from engine.digest_builder import build_digest_text
m=[dict(sender_name='Ana R',sender_email='ana@x.com',topic='Housing',message='Rent increases are pushing me out.',submitted_at='2026-07-25'),
   dict(sender_name='Ben K',sender_email='ben@x.com',topic='Housing',message='Landlord ignored three heat complaints.',submitted_at='2026-07-26'),
   dict(sender_name='Cy L',sender_email='cy@x.com',topic='Transit',message='The M14 is unusable at rush hour.',submitted_at='2026-07-26')]
print(build_digest_text(district=1, council_member_name='Christopher Marte', messages=m))"
```

**Then, in order:** (1) review the uncommitted Stage 1 code against §4, (2) **commit it**, (3) wire the LLM summarizer with §4.2's quote-anchoring guardrails, (4) show Elliot the rendered digest. Do not start Stage 2 until the domain and Resend account exist.
