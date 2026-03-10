# stealth-fetch

Production-grade anti-detection HTTP toolkit for Python. Battle-tested against Cloudflare, Akamai, and custom bot detection systems.

Stop cobbling together proxy rotation, circuit breakers, and fingerprint spoofing from Stack Overflow. This is the complete stack, extracted from a production system that makes thousands of API calls daily through hostile environments.

## How it works

```
                        ┌─────────────────────────────────────────────┐
                        │              YOUR APPLICATION               │
                        └─────────────────┬───────────────────────────┘
                                          │
                                   fetch(url, session_key)
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
          ┌─────────────────┐  ┌───────────────────┐  ┌─────────────────┐
          │   ProxyPool     │  │ BrowserFingerprint │  │  RequestQueue   │
          │                 │  │                    │  │                 │
          │ Acquire sticky  │  │ Generate unique    │  │ Rate limit:     │
          │ residential IP  │  │ Chrome identity    │  │ 1 login/5min    │
          │ per session     │  │ per session        │  │ 3 concurrent    │
          │                 │  │                    │  │ API calls       │
          │ ┌─────────────┐ │  │ • User-Agent       │  │                 │
          │ │ BrightData  │ │  │ • sec-ch-ua        │  │ acquire_slot()  │
          │ │ Oxylabs     │ │  │ • TLS fingerprint  │  │ release_slot()  │
          │ │ Generic     │ │  │   (curl_cffi)      │  │ wait_for_slot() │
          │ └─────────────┘ │  │                    │  │                 │
          └────────┬────────┘  └────────┬───────────┘  └────────┬────────┘
                   │                    │                       │
                   └────────────────────┼───────────────────────┘
                                        │
                                        ▼
                              ┌───────────────────┐
                              │  CircuitBreaker    │
                              │                    │
                              │ CLOSED ──► OPEN    │
                              │   ▲          │     │
                              │   │          ▼     │
                              │   └── HALF_OPEN    │
                              │                    │
                              │ Per-service or     │
                              │ per-proxy isolation │
                              └─────────┬─────────┘
                                        │
                                        ▼
                    ┌───────────────────────────────────────────┐
                    │              TARGET API                    │
                    │                                           │
                    │  Cloudflare / Akamai / Custom WAF         │
                    │                                           │
                    │  Sees: unique IP + unique browser +       │
                    │        human-like request patterns         │
                    └───────────────────┬───────────────────────┘
                                        │
                              ┌─────────┴─────────┐
                              │  403 / blocked?    │
                              └─────────┬─────────┘
                                        │
                        ┌───────── YES ─┴─ NO ──────────┐
                        │                                │
                        ▼                                ▼
              ┌───────────────────┐            ┌─────────────────┐
              │  pool.rotate()    │            │  Response ✓     │
              │  Burn IP, get     │            │  Circuit resets  │
              │  fresh session    │            │  Slot released   │
              └───────────────────┘            └─────────────────┘

                    ┌───────────────────────────────────────────┐
                    │          KV Store (shared state)           │
                    │                                           │
                    │  Dev:  In-memory dict with TTL            │
                    │  Prod: Redis (set REDIS_URL)              │
                    │                                           │
                    │  Stores: proxy sessions, burned IPs,      │
                    │  circuit states, fingerprints, rate limits │
                    └───────────────────────────────────────────┘
```

## What's inside

| Component | What it does |
|---|---|
| **ProxyPool** | Residential proxy management with sticky sessions (BrightData, Oxylabs, generic) |
| **CircuitBreaker** | Per-service failure isolation — stops cascading failures, auto-recovers |
| **BrowserFingerprint** | Consistent browser identity generation with curl_cffi TLS impersonation |
| **RequestQueue** | Per-session rate limiting and concurrency control |
| **KV** | Unified Redis/in-memory store — Redis in prod, dict in dev, zero config |
| **sanitize** | Input sanitization utilities (XSS, injection, control chars) |

## Install

```bash
pip install stealth-fetch
```

With optional dependencies:

```bash
pip install stealth-fetch[redis]     # Redis-backed state persistence
pip install stealth-fetch[curl]      # TLS fingerprint impersonation via curl_cffi
pip install stealth-fetch[httpx]     # httpx for async HTTP
pip install stealth-fetch[all]       # Everything
```

## Quick start

### Proxy pool with sticky sessions

Each session gets a dedicated residential IP. The target sees consistent source IPs per user — like a real person on their home WiFi.

```python
from stealth_fetch import ProxyPool

pool = ProxyPool(
    proxy_urls=["http://brd-customer-XXX-zone-residential:PASS@brd.superproxy.io:22225"],
    provider="brightdata",  # or "oxylabs" or "generic"
)

# Acquire a sticky session
session = pool.acquire(session_key="user-42")
print(session.proxy_url)  # URL with session ID injected for IP stickiness

# Got detected? Rotate to a new IP
new_session = pool.rotate(session_key="user-42", reason="cloudflare_detected")

# Done
pool.release(session_key="user-42")
```

Direct connection mode (no proxy) works automatically when no URLs are configured — great for local development.

### Circuit breaker

Prevents cascading failures. After N consecutive failures, the circuit opens and rejects calls immediately. After a cooldown, one test call is allowed to check recovery.

```python
from stealth_fetch import CircuitBreaker, CircuitOpenError

breaker = CircuitBreaker("target-api", failure_threshold=3, recovery_timeout=300)

try:
    async with breaker:
        response = await httpx.get("https://target-api.com/data")
except CircuitOpenError as e:
    print(f"Circuit open — retry in {e.retry_after:.0f}s")
```

Per-proxy circuit breakers isolate failures to individual IPs:

```python
# One burned proxy doesn't block other users
breaker = CircuitBreaker(f"api:proxy:{proxy_session_id}")
```

### Browser fingerprinting

Generate unique, consistent browser identities per session. Prevents the "500 requests with identical User-Agent" detection pattern.

```python
from stealth_fetch import generate_fingerprint, get_or_create_fingerprint

# Random fingerprint
fp = generate_fingerprint()
print(fp.user_agent)       # Mozilla/5.0 (Macintosh; ...) Chrome/128.0.0.0 Safari/537.36
print(fp.to_headers())     # {"user-agent": ..., "sec-ch-ua": ..., "sec-ch-ua-platform": ...}
print(fp.curl_impersonate) # "chrome124" — for curl_cffi TLS impersonation

# Persistent fingerprint — same key always returns same identity
fp = get_or_create_fingerprint("session:user-42")
```

With curl_cffi for real TLS fingerprint impersonation:

```python
from curl_cffi.requests import AsyncSession

fp = generate_fingerprint()

async with AsyncSession(
    impersonate=fp.curl_impersonate,
    headers=fp.to_headers(),
) as session:
    response = await session.get("https://target.com")
```

### Rate limiting

Enforce realistic request patterns to avoid detection.

```python
from stealth_fetch import acquire_slot, release_slot, wait_for_slot

# Login rate limiting — max 1 login per 5 minutes per session
if acquire_slot(session_id, "login"):
    await do_login()

# API concurrency — max 3 parallel calls per session
if acquire_slot(session_id, "api"):
    try:
        await make_api_call()
    finally:
        release_slot(session_id, "api")

# Or block until a slot opens
if await wait_for_slot(session_id, "api", timeout=30):
    ...
```

### Full stack example

All components working together:

```python
import httpx
from stealth_fetch import (
    ProxyPool, CircuitBreaker, CircuitOpenError,
    generate_fingerprint, acquire_slot, release_slot,
)

pool = ProxyPool()
breaker = CircuitBreaker("target", failure_threshold=3, recovery_timeout=60)

async def fetch(url: str, session_key: str):
    proxy = pool.acquire(session_key=session_key)
    fp = generate_fingerprint()

    if not acquire_slot(proxy.session_id, "api"):
        return None  # Rate limited

    try:
        async with breaker:
            async with httpx.AsyncClient(
                proxy=proxy.proxy_url,
                headers=fp.to_headers(),
            ) as client:
                return await client.get(url)
    except CircuitOpenError:
        return None  # Service down, back off
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            pool.rotate(session_key, reason="403")
        raise
    finally:
        release_slot(proxy.session_id, "api")
```

## State management

All components use a unified KV store for state persistence.

**Development**: In-memory dict with TTL support. Zero config needed.

**Production**: Set `REDIS_URL` environment variable and install `redis`:

```bash
export REDIS_URL="redis://localhost:6379/0"
pip install stealth-fetch[redis]
```

State is shared across workers and survives restarts when using Redis. The in-memory fallback works for single-process deployments and testing.

You can also inject your own KV store:

```python
from stealth_fetch.kv import create_kv, MemoryKV

# Custom Redis URL
store = create_kv("redis://custom-host:6379/1")

# Or use a fresh in-memory store (useful for testing)
store = MemoryKV()

# Pass to any component
pool = ProxyPool(kv_store=store)
breaker = CircuitBreaker("svc", kv_store=store)
fp = get_or_create_fingerprint("key", kv_store=store)
```

## Proxy provider support

| Provider | Session stickiness | Config |
|---|---|---|
| **BrightData** | `-session-{id}` in username | `provider="brightdata"` |
| **Oxylabs** | `-sessid-{id}` in username | `provider="oxylabs"` |
| **Generic** | Round-robin, no stickiness | `provider="generic"` |
| **Direct** | No proxy (dev mode) | No URLs configured |

Environment variable config:

```bash
export PROXY_POOL_URLS="http://brd-customer-XXX-zone-res:PASS@brd.superproxy.io:22225"
export PROXY_PROVIDER="brightdata"
```

Multiple proxy URLs (comma-separated) are load-balanced via round-robin.

## Testing

```bash
pip install stealth-fetch[dev]
pytest
```

All tests use the in-memory KV store — no Redis required.

## Design principles

- **Zero-config development**: Everything falls back to in-memory/direct mode. No Redis, no proxies, no env vars needed to run locally.
- **Production-ready**: Redis-backed state, proper TTLs, per-proxy isolation, async-native.
- **Composable**: Use any component independently or wire them together. No framework lock-in.
- **No magic**: Explicit state management. You control when to rotate, when to release, when to retry.

## Origin

Extracted from a production system that makes thousands of daily API calls through Cloudflare-protected endpoints.

## License

MIT
