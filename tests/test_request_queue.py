"""Tests for the request queue / rate limiter."""

import pytest
from stealth_fetch.kv import MemoryKV
from stealth_fetch.request_queue import acquire_slot, release_slot, wait_for_slot


def test_login_cooldown():
    store = MemoryKV()
    assert acquire_slot("sess1", "login", kv_store=store, login_cooldown=5) is True
    assert acquire_slot("sess1", "login", kv_store=store, login_cooldown=5) is False


def test_api_concurrency():
    store = MemoryKV()
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is True
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is True
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is False


def test_release_frees_slot():
    store = MemoryKV()
    # Fill 2 of 2 slots
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is True
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is True
    # Third should be denied
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is False

    # Release one slot
    release_slot("sess1", "api", kv_store=store)
    # Now we can acquire again
    assert acquire_slot("sess1", "api", kv_store=store, max_concurrent=2) is True


def test_login_release_is_noop():
    store = MemoryKV()
    acquire_slot("sess1", "login", kv_store=store, login_cooldown=5)
    release_slot("sess1", "login", kv_store=store)  # Should not error
    # Login is still on cooldown (TTL-based)
    assert acquire_slot("sess1", "login", kv_store=store, login_cooldown=5) is False


@pytest.mark.asyncio
async def test_wait_for_slot_immediate():
    store = MemoryKV()
    result = await wait_for_slot("sess1", "api", timeout=1, kv_store=store, max_concurrent=3)
    assert result is True


@pytest.mark.asyncio
async def test_wait_for_slot_timeout():
    store = MemoryKV()
    # Fill all slots
    for _ in range(3):
        acquire_slot("sess1", "api", kv_store=store, max_concurrent=3)

    # Should timeout
    result = await wait_for_slot("sess1", "api", timeout=0.5, kv_store=store, max_concurrent=3)
    assert result is False
