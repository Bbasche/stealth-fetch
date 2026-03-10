"""Residential proxy pool with sticky sessions.

Each session gets a dedicated proxy assignment (sticky IP) so the target sees
consistent source IPs per user — like a real person on their home WiFi.

Supports BrightData, Oxylabs, and generic (round-robin) proxy providers.
Falls back to direct connection when no proxy URLs are configured.

Usage:
    from stealth_fetch import ProxyPool

    pool = ProxyPool(
        proxy_urls=["http://brd-customer-XXX-zone-residential:PASS@brd.superproxy.io:22225"],
        provider="brightdata",
    )

    session = pool.acquire(session_key="user-42")
    print(session.proxy_url)  # Sticky proxy URL with session ID injected

    pool.rotate(session_key="user-42", reason="cloudflare_detected")
    pool.release(session_key="user-42")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass

from .kv import kv as _default_kv, KV

logger = logging.getLogger("stealth_fetch.proxy_pool")


@dataclass
class ProxySession:
    """A proxy assignment for a session."""

    session_id: str
    proxy_url: str | None  # None = direct connection
    provider: str


class ProxyPool:
    """Manages residential proxy assignments with sticky sessions.

    Args:
        proxy_urls: List of proxy base URLs. If empty or None, uses direct connection.
        provider: Proxy provider name. Determines how session IDs are injected.
            - "brightdata": Injects `-session-{id}` into username
            - "oxylabs": Injects `-sessid-{id}` into username
            - "generic": Uses URLs as-is (round-robin, no stickiness)
        kv_store: Optional KV store for session persistence. Defaults to module KV.
    """

    def __init__(
        self,
        proxy_urls: list[str] | str | None = None,
        provider: str = "brightdata",
        kv_store: KV | None = None,
    ):
        self._kv = kv_store or _default_kv
        self._rr_index: int = 0

        # Parse proxy URLs
        if proxy_urls is None:
            raw = os.getenv("PROXY_POOL_URLS", "")
            self._base_urls = [u.strip() for u in raw.split(",") if u.strip()]
        elif isinstance(proxy_urls, str):
            self._base_urls = [proxy_urls]
        else:
            self._base_urls = list(proxy_urls)

        self._provider = provider or os.getenv("PROXY_PROVIDER", "brightdata")

        if self._base_urls:
            logger.info(
                "ProxyPool: %d URL(s), provider=%s",
                len(self._base_urls), self._provider,
            )
        else:
            logger.info("ProxyPool: no proxy URLs — direct connection mode")

    @property
    def is_direct(self) -> bool:
        """True if no proxy URLs are configured (direct connection mode)."""
        return len(self._base_urls) == 0

    def _build_session_url(self, base_url: str, session_id: str) -> str:
        """Inject session ID into the proxy URL for sticky IP assignment."""
        if self._provider == "brightdata":
            if "-session-" in base_url:
                return re.sub(r"-session-[^:]+", f"-session-{session_id}", base_url)
            at_idx = base_url.index("@")
            colon_idx = base_url.rindex(":", 0, at_idx)
            return f"{base_url[:colon_idx]}-session-{session_id}{base_url[colon_idx:]}"

        elif self._provider == "oxylabs":
            if "-sessid-" in base_url:
                return re.sub(r"-sessid-[^:]+", f"-sessid-{session_id}", base_url)
            at_idx = base_url.index("@")
            colon_idx = base_url.rindex(":", 0, at_idx)
            return f"{base_url[:colon_idx]}-sessid-{session_id}{base_url[colon_idx:]}"

        else:
            return base_url

    def _pick_base_url(self) -> str:
        """Round-robin across base URLs."""
        url = self._base_urls[self._rr_index % len(self._base_urls)]
        self._rr_index += 1
        return url

    def acquire(self, session_key: str, session_id: str | None = None) -> ProxySession:
        """Get or restore a proxy session.

        Args:
            session_key: Unique key for this session (e.g. user ID, account ID).
            session_id: If provided, restore this session unless it's been burned.

        Returns:
            ProxySession with sticky proxy URL (or None for direct mode).
        """
        if not self._base_urls:
            return ProxySession(
                session_id=session_id or str(uuid.uuid4())[:12],
                proxy_url=None,
                provider="direct",
            )

        redis_key = f"proxy:session:{session_key}"

        # Try to restore existing session
        if session_id:
            burned_key = f"proxy:burned:{session_id}"
            if not self._kv.get(burned_key):
                base_url = self._pick_base_url()
                proxy_url = self._build_session_url(base_url, session_id)
                self._kv.set(redis_key, json.dumps({
                    "session_id": session_id,
                    "provider": self._provider,
                }))
                return ProxySession(
                    session_id=session_id,
                    proxy_url=proxy_url,
                    provider=self._provider,
                )
            logger.info("Session %s is burned — assigning fresh", session_id)

        # Assign fresh session
        new_id = str(uuid.uuid4()).replace("-", "")[:16]
        base_url = self._pick_base_url()
        proxy_url = self._build_session_url(base_url, new_id)

        self._kv.set(redis_key, json.dumps({
            "session_id": new_id,
            "provider": self._provider,
        }))

        logger.info("Proxy assigned: key=%s session=%s", session_key, new_id[:8])

        return ProxySession(
            session_id=new_id,
            proxy_url=proxy_url,
            provider=self._provider,
        )

    def rotate(self, session_key: str, reason: str = "unknown") -> ProxySession:
        """Burn current proxy IP and assign a fresh session.

        Args:
            session_key: Session key to rotate.
            reason: Why we're rotating (logged for debugging).

        Returns:
            New ProxySession with different sticky IP.
        """
        redis_key = f"proxy:session:{session_key}"
        raw = self._kv.get(redis_key)

        if raw:
            old = json.loads(raw)
            old_id = old.get("session_id", "")
            # Burn the old session for 24 hours
            self._kv.set(f"proxy:burned:{old_id}", "1", ttl=86400)
            logger.warning("Proxy rotated: key=%s old=%s reason=%s", session_key, old_id[:8], reason)

        self._kv.delete(redis_key)
        return self.acquire(session_key)

    def release(self, session_key: str) -> None:
        """Clean up proxy assignment."""
        redis_key = f"proxy:session:{session_key}"
        self._kv.delete(redis_key)
        logger.info("Proxy released: key=%s", session_key)

    async def health_check(self, test_url: str = "https://httpbin.org/ip") -> dict[int, bool]:
        """Test connectivity of all proxy base URLs.

        Returns:
            Dict mapping base URL index to health status (True = reachable).
        """
        import httpx

        results: dict[int, bool] = {}
        for i, base_url in enumerate(self._base_urls):
            try:
                test_session_id = f"healthcheck-{uuid.uuid4().hex[:8]}"
                test_proxy = self._build_session_url(base_url, test_session_id)
                async with httpx.AsyncClient(proxy=test_proxy, timeout=10.0) as client:
                    resp = await client.get(test_url)
                    results[i] = resp.status_code == 200
            except Exception:
                results[i] = False
        return results
