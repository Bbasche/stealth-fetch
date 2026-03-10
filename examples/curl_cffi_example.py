"""Example: Using stealth-fetch with curl_cffi for TLS fingerprint impersonation.

curl_cffi can impersonate real browser TLS fingerprints (JA3/JA4), which is
critical for bypassing advanced bot detection that checks TLS handshake patterns.
"""

import asyncio
from stealth_fetch import ProxyPool, generate_fingerprint

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    print("Install curl_cffi for TLS fingerprint impersonation: pip install curl_cffi")


async def fetch_with_tls_impersonation(url: str):
    """Fetch a URL with full TLS fingerprint impersonation."""
    if not HAS_CURL_CFFI:
        print("curl_cffi not installed — skipping")
        return

    pool = ProxyPool()
    proxy = pool.acquire(session_key="tls-demo")
    fp = generate_fingerprint()

    print(f"Impersonating: {fp.curl_impersonate}")
    print(f"User-Agent: {fp.user_agent}")

    async with AsyncSession(
        impersonate=fp.curl_impersonate,
        proxy=proxy.proxy_url,
        headers=fp.to_headers(),
    ) as session:
        response = await session.get(url)
        print(f"[{response.status_code}] {url}")
        print(f"Response headers: {dict(list(response.headers.items())[:5])}...")

    pool.release(session_key="tls-demo")


async def main():
    await fetch_with_tls_impersonation("https://tls.browserleaks.com/json")


if __name__ == "__main__":
    asyncio.run(main())
