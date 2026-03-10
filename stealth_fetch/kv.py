"""Unified Redis / in-memory key-value store.

Provides a single interface that uses Redis in production and falls back to an
in-memory dict with TTL support in development. Zero-config: if REDIS_URL is
set in the environment, Redis is used automatically.

Usage:
    from stealth_fetch import kv

    kv.set("session:abc", "data", ttl=300)
    value = kv.get("session:abc")
    kv.delete("session:abc")

Or bring your own Redis URL:
    from stealth_fetch.kv import create_kv
    store = create_kv("redis://localhost:6379/0")
"""

from __future__ import annotations

import fnmatch
import os
import time
from typing import Any, Protocol


class KV(Protocol):
    """Key-value store interface."""

    def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    def get(self, key: str) -> str | None: ...
    def delete(self, key: str) -> None: ...
    def keys(self, pattern: str = "*") -> list[str]: ...
    def incr(self, key: str) -> int: ...
    def expire(self, key: str, ttl: int) -> None: ...
    def ttl(self, key: str) -> int: ...


class MemoryKV:
    """Dict-based KV store with TTL support. For development and testing."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}

    def _evict(self, key: str) -> None:
        entry = self._data.get(key)
        if entry and entry[1] is not None and time.time() > entry[1]:
            del self._data[key]

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires = (time.time() + ttl) if ttl else None
        self._data[key] = (value, expires)

    def get(self, key: str) -> str | None:
        self._evict(key)
        entry = self._data.get(key)
        return entry[0] if entry else None

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def keys(self, pattern: str = "*") -> list[str]:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp is not None and now > exp]
        for k in expired:
            del self._data[k]
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]

    def incr(self, key: str) -> int:
        self._evict(key)
        entry = self._data.get(key)
        if entry is None:
            self._data[key] = ("1", None)
            return 1
        new_val = int(entry[0]) + 1
        self._data[key] = (str(new_val), entry[1])
        return new_val

    def expire(self, key: str, ttl: int) -> None:
        entry = self._data.get(key)
        if entry is not None:
            self._data[key] = (entry[0], time.time() + ttl)

    def ttl(self, key: str) -> int:
        self._evict(key)
        entry = self._data.get(key)
        if entry is None:
            return -2
        if entry[1] is None:
            return -1
        return max(0, int(entry[1] - time.time()))


class RedisKV:
    """Wraps a Redis connection with the same interface as MemoryKV."""

    def __init__(self, conn: Any) -> None:
        self._r = conn

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl:
            self._r.setex(key, ttl, value)
        else:
            self._r.set(key, value)

    def get(self, key: str) -> str | None:
        return self._r.get(key)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def keys(self, pattern: str = "*") -> list[str]:
        return self._r.keys(pattern)

    def incr(self, key: str) -> int:
        return self._r.incr(key)

    def expire(self, key: str, ttl: int) -> None:
        self._r.expire(key, ttl)

    def ttl(self, key: str) -> int:
        return self._r.ttl(key)


def create_kv(redis_url: str | None = None) -> MemoryKV | RedisKV:
    """Create a KV store instance.

    Args:
        redis_url: Redis connection URL. If None, checks REDIS_URL env var.
                   Falls back to in-memory store if neither is available.
    """
    url = redis_url or os.getenv("REDIS_URL")

    if url:
        try:
            import redis as _redis_lib
            conn = _redis_lib.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            conn.ping()
            return RedisKV(conn)
        except Exception:
            pass

    return MemoryKV()


# Module-level singleton — auto-connects to Redis if REDIS_URL is set
kv: MemoryKV | RedisKV = create_kv()
