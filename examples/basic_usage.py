"""Basic usage of stealth-fetch components."""

import asyncio
from stealth_fetch import (
    ProxyPool,
    CircuitBreaker,
    generate_fingerprint,
    get_or_create_fingerprint,
    acquire_slot,
    release_slot,
    wait_for_slot,
)


async def main():
    # ---- 1. Browser Fingerprint Generation ----
    # Generate a random fingerprint for a new session
    fp = generate_fingerprint()
    print(f"User-Agent: {fp.user_agent}")
    print(f"sec-ch-ua: {fp.sec_ch_ua}")
    print(f"curl_cffi target: {fp.curl_impersonate}")
    print(f"Headers: {fp.to_headers()}")
    print()

    # Persistent fingerprint — same key always returns same identity
    fp1 = get_or_create_fingerprint("user:42")
    fp2 = get_or_create_fingerprint("user:42")
    assert fp1.user_agent == fp2.user_agent
    print(f"Persistent fingerprint for user:42 = Chrome {fp1.chrome_version} on {fp1.os_name}")
    print()

    # ---- 2. Proxy Pool ----
    # Direct mode (no proxy URLs configured)
    pool = ProxyPool()
    session = pool.acquire(session_key="user-42")
    print(f"Direct mode: proxy_url={session.proxy_url}, provider={session.provider}")
    pool.release(session_key="user-42")
    print()

    # With BrightData proxy
    pool = ProxyPool(
        proxy_urls=["http://brd-customer-XXXXX-zone-residential:PASSWORD@brd.superproxy.io:22225"],
        provider="brightdata",
    )
    session = pool.acquire(session_key="user-42")
    print(f"BrightData session: {session.session_id[:8]}...")
    print(f"Proxy URL: {session.proxy_url}")

    # Rotate on detection
    new_session = pool.rotate(session_key="user-42", reason="cloudflare_detected")
    print(f"Rotated to: {new_session.session_id[:8]}...")
    pool.release(session_key="user-42")
    print()

    # ---- 3. Circuit Breaker ----
    breaker = CircuitBreaker("target-api", failure_threshold=3, recovery_timeout=10)

    # Successful call
    async with breaker:
        print(f"Call succeeded. State: {breaker.state}, failures: {breaker.failure_count}")

    # Simulate failures
    for i in range(3):
        try:
            async with breaker:
                raise ConnectionError(f"Failure #{i + 1}")
        except ConnectionError:
            print(f"Failure #{i + 1}. State: {breaker.state}, failures: {breaker.failure_count}")

    # Circuit is now open
    from stealth_fetch import CircuitOpenError
    try:
        async with breaker:
            pass
    except CircuitOpenError as e:
        print(f"Circuit open! Retry after {e.retry_after:.0f}s")

    breaker.reset()
    print(f"After reset: state={breaker.state}")
    print()

    # ---- 4. Rate Limiting ----
    session_id = "proxy-session-abc"

    # Login rate limiting (1 per 5 minutes)
    got_slot = acquire_slot(session_id, "login", login_cooldown=5)
    print(f"First login slot: {got_slot}")  # True

    got_slot = acquire_slot(session_id, "login", login_cooldown=5)
    print(f"Second login slot (within cooldown): {got_slot}")  # False

    # API concurrency limiting (max 3)
    slots = []
    for i in range(4):
        ok = acquire_slot(session_id, "api", max_concurrent=3)
        slots.append(ok)
        print(f"API slot #{i + 1}: {ok}")  # True, True, True, False

    # Release slots
    for _ in range(3):
        release_slot(session_id, "api")

    # Async wait for slot
    ok = await wait_for_slot(session_id, "api", timeout=2)
    print(f"Wait for slot: {ok}")
    if ok:
        release_slot(session_id, "api")


if __name__ == "__main__":
    asyncio.run(main())
