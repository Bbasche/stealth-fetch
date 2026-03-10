"""Tests for the in-memory KV store."""

import time
from stealth_fetch.kv import MemoryKV


def test_set_get():
    store = MemoryKV()
    store.set("key1", "value1")
    assert store.get("key1") == "value1"


def test_get_missing():
    store = MemoryKV()
    assert store.get("missing") is None


def test_delete():
    store = MemoryKV()
    store.set("key1", "value1")
    store.delete("key1")
    assert store.get("key1") is None


def test_ttl_expiry():
    store = MemoryKV()
    store.set("key1", "value1", ttl=1)
    assert store.get("key1") == "value1"
    time.sleep(1.1)
    assert store.get("key1") is None


def test_incr():
    store = MemoryKV()
    assert store.incr("counter") == 1
    assert store.incr("counter") == 2
    assert store.incr("counter") == 3


def test_keys_pattern():
    store = MemoryKV()
    store.set("user:1", "a")
    store.set("user:2", "b")
    store.set("session:1", "c")
    assert sorted(store.keys("user:*")) == ["user:1", "user:2"]


def test_expire():
    store = MemoryKV()
    store.set("key1", "value1")
    store.expire("key1", 1)
    assert store.get("key1") == "value1"
    time.sleep(1.1)
    assert store.get("key1") is None


def test_ttl_returns_remaining():
    store = MemoryKV()
    store.set("key1", "value1", ttl=10)
    remaining = store.ttl("key1")
    assert 8 <= remaining <= 10


def test_ttl_missing_key():
    store = MemoryKV()
    assert store.ttl("missing") == -2


def test_ttl_no_expiry():
    store = MemoryKV()
    store.set("key1", "value1")
    assert store.ttl("key1") == -1
