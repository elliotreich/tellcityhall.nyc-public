"""Tests for the digest message queue (SQLite persistence)."""
import os
import tempfile
from pathlib import Path

import pytest

import config as app_config
from engine.queue import (
    init_db,
    enqueue,
    pending_for_district,
    get_pending_count,
    get_districts_with_pending,
    create_digest,
    mark_sent,
    mark_failed,
    get_message_by_token,
    verify_message,
)


@pytest.fixture(autouse=True)
def _temp_db():
    """Point DIGEST_DB_PATH at a temporary file for each test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    original = app_config.DIGEST_DB_PATH
    app_config.DIGEST_DB_PATH = Path(tmp.name)
    init_db()
    yield
    app_config.DIGEST_DB_PATH = original
    if os.path.exists(tmp.name):
        os.unlink(tmp.name)


class TestEnqueue:
    def test_enqueue_returns_id_and_token(self):
        msg_id, token = enqueue(1, "Alice", "alice@test.com", "1 Main St", "Housing", "Fix rent.")
        assert msg_id
        assert len(msg_id) > 8
        assert token
        assert len(token) > 8

    def test_enqueue_stores_message(self):
        enqueue(1, "Alice", "alice@test.com", "1 Main St", "Housing", "Fix rent.")
        pending = pending_for_district(1, verified_only=False)
        assert len(pending) == 1
        assert pending[0]["sender_name"] == "Alice"
        assert pending[0]["verified"] == 0

    def test_enqueue_multiple_topics(self):
        enqueue(1, "Alice", "alice@test.com", "1 Main St", "Housing", "Fix rent.")
        enqueue(1, "Bob", "bob@test.com", "2 Main St", "Transportation", "Fix buses.")
        enqueue(1, "Carol", "carol@test.com", "3 Main St", "Housing", "More units.")
        pending = pending_for_district(1, verified_only=False)
        assert len(pending) == 3


class TestPendingForDistrict:
    def test_empty_district(self):
        pending = pending_for_district(99)
        assert pending == []

    def test_only_matching_district(self):
        enqueue(1, "Alice", "a@t.com", "Addr", "Topic", "Msg 1")
        enqueue(2, "Bob", "b@t.com", "Addr", "Topic", "Msg 2")
        pending = pending_for_district(1, verified_only=False)
        assert len(pending) == 1
        assert pending[0]["sender_name"] == "Alice"

    def test_verified_only_filter(self):
        msg_id1, token1 = enqueue(1, "Alice", "a@t.com", "Addr", "Topic", "Msg 1")
        msg_id2, token2 = enqueue(1, "Bob", "b@t.com", "Addr", "Topic", "Msg 2")
        verify_message(token1)

        pending_v = pending_for_district(1, verified_only=True)
        pending_all = pending_for_district(1, verified_only=False)

        assert len(pending_v) == 1
        assert pending_v[0]["sender_name"] == "Alice"
        assert len(pending_all) == 2


class TestGetPendingCount:
    def test_count_verified_only(self):
        _, t1 = enqueue(1, "A", "a@t.com", "A", "T", "M")
        _, t2 = enqueue(1, "B", "b@t.com", "A", "T", "M")
        verify_message(t1)
        assert get_pending_count(1, verified_only=True) == 1
        assert get_pending_count(1, verified_only=False) == 2

    def test_zero_pending(self):
        assert get_pending_count(99) == 0


class TestVerification:
    def test_verify_message_success(self):
        msg_id, token = enqueue(1, "Alice", "a@t.com", "Addr", "T", "Msg")
        assert get_message_by_token(token)["verified"] == 0
        assert verify_message(token) is True
        assert get_message_by_token(token)["verified"] == 1

    def test_verify_message_bad_token(self):
        assert verify_message("nonexistent") is False

    def test_verify_message_idempotent(self):
        _, token = enqueue(1, "A", "a@t.com", "A", "T", "M")
        assert verify_message(token) is True
        assert verify_message(token) is False  # already verified

    def test_get_message_by_token_nonexistent(self):
        assert get_message_by_token("bad_token") is None


class TestDigestLifecycle:
    def test_create_digest_queues_messages(self):
        enqueue(1, "A", "a@t.com", "A", "T", "M1")
        enqueue(1, "B", "b@t.com", "A", "T", "M2")
        msgs = pending_for_district(1, verified_only=False)
        msg_ids = [m["id"] for m in msgs]

        digest_id = create_digest(1, msg_ids)
        assert digest_id

        # Messages should now be 'queued', not 'pending'
        pending = pending_for_district(1, verified_only=False)
        assert len(pending) == 0

        # Verify via get_pending_count
        assert get_pending_count(1, verified_only=False) == 0

    def test_mark_sent(self):
        enqueue(1, "A", "a@t.com", "A", "T", "M1")
        enqueue(1, "B", "b@t.com", "A", "T", "M2")
        msgs = pending_for_district(1, verified_only=False)
        msg_ids = [m["id"] for m in msgs]
        digest_id = create_digest(1, msg_ids)
        mark_sent(msg_ids, digest_id)

        # All should be gone from pending
        assert get_pending_count(1, verified_only=False) == 0

    def test_mark_failed(self):
        enqueue(1, "A", "a@t.com", "A", "T", "M1")
        msgs = pending_for_district(1, verified_only=False)
        msg_ids = [m["id"] for m in msgs]
        digest_id = create_digest(1, msg_ids)
        mark_failed(msg_ids, digest_id)

        assert get_pending_count(1, verified_only=False) == 0

    def test_idempotent_no_double_send(self):
        """Same message should not be sent twice."""
        enqueue(1, "A", "a@t.com", "A", "T", "M1")
        msgs = pending_for_district(1, verified_only=False)
        msg_ids = [m["id"] for m in msgs]

        # First send
        d1 = create_digest(1, msg_ids)
        mark_sent(msg_ids, d1)

        # Second attempt should find no pending messages
        assert get_pending_count(1, verified_only=False) == 0
        assert pending_for_district(1, verified_only=False) == []


class TestGetDistrictsWithPending:
    def test_returns_districts(self):
        enqueue(1, "A", "a@t.com", "A", "T", "M")
        enqueue(3, "B", "b@t.com", "A", "T", "M")
        districts = get_districts_with_pending(verified_only=False)
        assert 1 in districts
        assert 3 in districts
        assert 2 not in districts

    def test_empty_when_all_verified(self):
        enqueue(1, "A", "a@t.com", "A", "T", "M")
        districts = get_districts_with_pending(verified_only=True)
        assert districts == []

    def test_after_verified(self):
        _, t = enqueue(1, "A", "a@t.com", "A", "T", "M")
        verify_message(t)
        districts = get_districts_with_pending(verified_only=True)
        assert 1 in districts
