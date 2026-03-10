"""Per-session rate limiter and concurrency control.

Enforces realistic request patterns to avoid detection:
    - Login rate limiting: max 1 login per session per cooldown period
    - Concurrency limiting: max N parallel API calls per session

Uses the KV store for shared state (Redis in prod, in-memory in dev).

Usage:
    from stealth_fetch import acquire_slot, release_slot, wait_for_slot

    # Try to acquire a slot (non-blocking)
    if acquire_slot("session-abc", "login"):
        try:
            await do_login()
        finally:
            release_slot("session-abc", "login")

    # Block until a slot is available
    if await wait_for_slot("session-abc", "api"):
        try:
            await make_api_call()
        finally:
            release_slot("session-abc", "api")
"""

from __future__ import annotations

import asyncio
import logging

from .kv import kv as _default_kv, KV

logger = logging.getLogger("stealth_fetch.request_queue")

# -- Configuration -----------------------------------------------------------
LOGIN_COOLDOWN = 300        # 5 minutes between logins per session
MAX_CONCURRENT_API = 3      # Max parallel API calls per session
CONCURRENT_SLOT_TTL = 60    # Safety TTL — auto-clears stuck slots


def acquire_slot(
    session_id: str,
    slot_type: str = "api",
    kv_store: KV | None = None,
    login_cooldown: int = LOGIN_COOLDOWN,
    max_concurrent: int = MAX_CONCURRENT_API,
) -> bool:
    """Try to acquire a rate-limit slot.

    Args:
        session_id: Session identifier (e.g. proxy session ID).
        slot_type: "login" (1 per cooldown) or "api" (max N concurrent).
        kv_store: Optional KV store. Defaults to module KV.
        login_cooldown: Seconds between logins per session.
        max_concurrent: Max parallel API calls per session.

    Returns:
        True if slot acquired, False if rate-limited.
    """
    store = kv_store or _default_kv

    if slot_type == "login":
        key = f"rq:login:{session_id}"
        if store.get(key):
            remaining = store.ttl(key)
            logger.debug("Login rate-limited for %s (retry in %ds)", session_id[:8], remaining)
            return False
        store.set(key, "1", ttl=login_cooldown)
        return True

    # API slot — check then increment
    key = f"rq:concurrent:{session_id}"
    raw = store.get(key)
    current = int(raw) if raw else 0

    if current >= max_concurrent:
        logger.debug("API rate-limited for %s (%d/%d)", session_id[:8], current, max_concurrent)
        return False

    store.set(key, str(current + 1), ttl=CONCURRENT_SLOT_TTL)
    return True


def release_slot(
    session_id: str,
    slot_type: str = "api",
    kv_store: KV | None = None,
) -> None:
    """Release a rate-limit slot after a call completes.

    For login slots: no-op (TTL handles expiry).
    For API slots: decrements the concurrent counter.
    """
    if slot_type == "login":
        return

    store = kv_store or _default_kv
    key = f"rq:concurrent:{session_id}"
    raw = store.get(key)
    if raw:
        count = int(raw)
        if count > 1:
            store.set(key, str(count - 1), ttl=CONCURRENT_SLOT_TTL)
        else:
            store.delete(key)


async def wait_for_slot(
    session_id: str,
    slot_type: str = "api",
    timeout: float = 30,
    kv_store: KV | None = None,
    **kwargs,
) -> bool:
    """Poll until a rate-limit slot is available.

    Args:
        session_id: Session identifier.
        slot_type: "login" or "api".
        timeout: Max seconds to wait.
        kv_store: Optional KV store.
        **kwargs: Passed to acquire_slot (login_cooldown, max_concurrent).

    Returns:
        True if slot acquired within timeout, False if timed out.
    """
    elapsed = 0.0
    interval = 0.5

    while elapsed < timeout:
        if acquire_slot(session_id, slot_type, kv_store=kv_store, **kwargs):
            return True
        await asyncio.sleep(interval)
        elapsed += interval

    logger.warning("Rate-limit wait timed out: session=%s type=%s (%.1fs)", session_id[:8], slot_type, timeout)
    return False
