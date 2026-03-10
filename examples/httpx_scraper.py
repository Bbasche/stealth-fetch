"""Example: Using stealth-fetch with httpx for anti-detection web scraping."""

import asyncio
import httpx
from stealth_fetch import (
    ProxyPool,
    CircuitBreaker,
    CircuitOpenError,
    generate_fingerprint,
    acquire_slot,
    release_slot,
)


async def fetch_with_stealth(url: str, session_key: str = "default"):
    """Fetch a URL using the full stealth stack."""

    # 1. Get a proxy session
    pool = ProxyPool()  # Reads PROXY_POOL_URLS from env
    proxy = pool.acquire(session_key=session_key)

    # 2. Generate a consistent browser fingerprint
    fp = generate_fingerprint()

    # 3. Check circuit breaker
    breaker = CircuitBreaker(f"scraper:{session_key}", failure_threshold=3, recovery_timeout=60)

    # 4. Rate limit
    if not acquire_slot(proxy.session_id, "api"):
        print("Rate limited — waiting...")
        await asyncio.sleep(1)

    try:
        async with breaker:
            async with httpx.AsyncClient(
                proxy=proxy.proxy_url,
                headers=fp.to_headers(),
                timeout=15.0,
            ) as client:
                response = await client.get(url)
                print(f"[{response.status_code}] {url}")
                print(f"  Proxy: {proxy.provider} (session: {proxy.session_id[:8]})")
                print(f"  Identity: Chrome {fp.chrome_version} on {fp.os_name}")
                return response

    except CircuitOpenError as e:
        print(f"Circuit open for {e.service} — retry in {e.retry_after:.0f}s")
        return None

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # Cloudflare/bot detection — rotate proxy
            print("403 detected — rotating proxy")
            pool.rotate(session_key=session_key, reason="403_forbidden")
        raise

    finally:
        release_slot(proxy.session_id, "api")


async def main():
    # Fetch multiple pages with different session identities
    urls = [
        "https://httpbin.org/headers",
        "https://httpbin.org/ip",
        "https://httpbin.org/user-agent",
    ]

    for i, url in enumerate(urls):
        await fetch_with_stealth(url, session_key=f"session-{i}")
        await asyncio.sleep(0.5)  # Jitter between requests


if __name__ == "__main__":
    asyncio.run(main())
