# NYC Bridge — Digest Mode Build Spec (v1)

Repo: `~/Projects/dev/nyc-bridge` (git is healthy, HEAD `f37cbc1`, 50 tests pass).
Work on a branch: `git checkout -b digest-mode`.

## Context
Today the app is **stateless and sends immediately**. Every NYC Council member
(51/51) has an email at `council.nyc.gov`. We are adding **digest mode**: instead of
firing one email per constituent message, messages are **queued**, then delivered
once per day per Council district as a single digest email.

Scope for v1 is **Council members ONLY** (all 51, `data/nyc_officials.yaml` key
`council`, keyed by district number 1-51). All other officials keep the existing
immediate-send behavior. **Do NOT touch `engine/form_submitter.py` or any Playwright
/ CAPTCHA code — it is out of scope.**

## Digest format (Elliot's design)
- **Page 1 — cover letter:** top-line takeaways and the policy matters raised, so a
  chief of staff can see what constituents care about without reading everything.
- **Subsequent pages — the raw constituent messages**, in full.
- Delivered at a time that suits an office (default 6:00am America/New_York, configurable).

## Build these

### 1. Persistence (`engine/queue.py`)
SQLite at `data/queue.db`. Table `pending_messages`:
`id, district, sender_name, sender_email, sender_address, topic, message,
submitted_at, status (pending|sent|failed), digest_id, verified (bool)`.
Plus a `digests` table: `id, district, sent_at, message_count, status`.
Functions: `enqueue(...)`, `pending_for_district(d)`, `mark_sent(ids, digest_id)`.
Use stdlib `sqlite3`. WAL mode. No ORM.

### 2. Cover-page renderer (`engine/digest_builder.py`) — HIGHEST RISK, READ CAREFULLY
Builds the digest. The cover page is **quote-anchored**:
- Deterministic parts (compute in code, never AI): total message count, per-topic
  tallies, date range.
- AI part: a SHORT prose summary per topic (2-3 sentences).
- **HARD RULE: every claim in AI prose must be traceable to an actual submitted
  message, and each topic summary must be accompanied by at least one verbatim
  quoted excerpt from a real message.** Never invent, infer, or extrapolate a
  constituent position. If messages in a topic are too few or too vague to
  summarize, emit the quotes alone with NO prose summary.
- Implement AI summarization behind a small interface with a **deterministic
  fallback** (quotes + tallies only) so the digest still builds if no LLM is
  configured. Default to the fallback if the LLM call fails or returns empty.
- Render to HTML (page 1 cover, then messages). Plain-text alternative too.

### 3. Low-volume rule
If a district has **fewer than 3 pending messages**, do NOT send an AI-summarized
digest — forward the messages plainly (a "digest" summarizing 1 message is worse
than the message). Make the threshold a config constant `DIGEST_MIN_FOR_SUMMARY = 3`.
If a district has **0** pending, send nothing at all.

### 4. Reply-To routing
The digest MUST let a chief of staff reply to the actual constituent. With one
constituent in a digest, set `Reply-To` to their address. With several, set
`Reply-To` to the sender and include each constituent's email clearly beside their
message. Never make the digest look like it came from nobody — that reads as astroturf.

### 5. Per-recipient-domain rate limiting
All 51 digests go to `council.nyc.gov` in one burst. Extend the limiter in
`engine/email_sender.py` to be **per-recipient-domain**, not just global, with a
configurable delay between sends to the same domain. Default: max 1 message per
2 seconds per domain.

### 6. Constituent email verification
Before a message is eligible for a digest, the constituent's email must be
confirmed. Add a token (`secrets.token_urlsafe`), a `verified` flag, and an
endpoint `GET /verify/{token}`. **Unverified messages are never included in a
digest.** This prevents one bad actor from getting the domain blocked.

### 7. Scheduler entry point
`scripts/send_digests.py` — iterate all 51 districts, build + send due digests,
log results. Must be safe to run repeatedly (idempotent: never send the same
queued message twice). Support `--dry-run` that renders without sending, and
`--district N` to target one. Do NOT install a cron/systemd timer; just the script.

### 8. Tests
Add `tests/test_queue.py`, `tests/test_digest_builder.py`, `tests/test_rate_limit.py`.
Cover: enqueue/dequeue, idempotency (no double-send), the <3 low-volume rule,
unverified exclusion, per-domain limiting, and that the deterministic fallback
produces a valid digest with no LLM. **The existing 50 tests must still pass.**

## Constraints
- Python 3.11, FastAPI, stdlib sqlite3. Match existing code style.
- Do NOT invent facts in any user- or office-facing copy.
- Do NOT modify README.md (handled separately).
- Do NOT git push. Commit to the `digest-mode` branch only.

## When done
Run `./.venv/bin/python -m pytest tests/ -q` and report: what you built, test
results (real numbers), and anything you could NOT do.
