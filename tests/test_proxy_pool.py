"""Tests for the proxy pool."""

from stealth_fetch.kv import MemoryKV
from stealth_fetch.proxy_pool import ProxyPool


def test_direct_mode():
    pool = ProxyPool(proxy_urls=[], kv_store=MemoryKV())
    session = pool.acquire(session_key="user-1")
    assert session.proxy_url is None
    assert session.provider == "direct"


def test_brightdata_session_injection():
    store = MemoryKV()
    pool = ProxyPool(
        proxy_urls=["http://brd-customer-XXX-zone-res:PASS@brd.superproxy.io:22225"],
        provider="brightdata",
        kv_store=store,
    )
    session = pool.acquire(session_key="user-1")
    assert session.proxy_url is not None
    assert f"-session-{session.session_id}" in session.proxy_url
    assert session.provider == "brightdata"


def test_oxylabs_session_injection():
    store = MemoryKV()
    pool = ProxyPool(
        proxy_urls=["http://customer-XXX:PASS@pr.oxylabs.io:7777"],
        provider="oxylabs",
        kv_store=store,
    )
    session = pool.acquire(session_key="user-1")
    assert session.proxy_url is not None
    assert f"-sessid-{session.session_id}" in session.proxy_url


def test_rotate_gives_new_session():
    store = MemoryKV()
    pool = ProxyPool(
        proxy_urls=["http://brd-customer-XXX-zone-res:PASS@brd.superproxy.io:22225"],
        provider="brightdata",
        kv_store=store,
    )
    s1 = pool.acquire(session_key="user-1")
    s2 = pool.rotate(session_key="user-1", reason="test")
    assert s1.session_id != s2.session_id


def test_burned_session_gets_new_ip():
    store = MemoryKV()
    pool = ProxyPool(
        proxy_urls=["http://brd-customer-XXX-zone-res:PASS@brd.superproxy.io:22225"],
        provider="brightdata",
        kv_store=store,
    )
    s1 = pool.acquire(session_key="user-1")
    pool.rotate(session_key="user-1", reason="burned")

    # Try to restore the old session ID — should get a new one
    s2 = pool.acquire(session_key="user-1", session_id=s1.session_id)
    assert s2.session_id != s1.session_id


def test_release():
    store = MemoryKV()
    pool = ProxyPool(proxy_urls=[], kv_store=store)
    pool.acquire(session_key="user-1")
    pool.release(session_key="user-1")
    # No error — release is idempotent


def test_round_robin():
    store = MemoryKV()
    pool = ProxyPool(
        proxy_urls=[
            "http://proxy1:PASS@host:1111",
            "http://proxy2:PASS@host:2222",
        ],
        provider="generic",
        kv_store=store,
    )
    s1 = pool.acquire(session_key="a")
    s2 = pool.acquire(session_key="b")
    # Generic doesn't inject session IDs, so URLs alternate
    assert "proxy1" in s1.proxy_url
    assert "proxy2" in s2.proxy_url
