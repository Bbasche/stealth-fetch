"""stealth-fetch: Production-grade anti-detection HTTP toolkit for Python.

A complete stealth HTTP stack for calling APIs that don't want to be called.
Battle-tested in production against Cloudflare, Akamai, and custom bot detection.

Components:
    - ProxyPool: Residential proxy management with sticky sessions
    - CircuitBreaker: Per-service/per-proxy failure isolation
    - BrowserFingerprint: Consistent browser identity generation (curl_cffi)
    - RequestQueue: Per-session rate limiting and concurrency control
    - KV: Unified Redis/in-memory key-value store
    - sanitize: Request body sanitization utilities
"""

from .kv import kv, KV, MemoryKV, RedisKV
from .proxy_pool import ProxyPool, ProxySession
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .fingerprint import generate_fingerprint, get_or_create_fingerprint, BrowserFingerprint
from .request_queue import acquire_slot, release_slot, wait_for_slot
from .sanitize import sanitize_string, sanitize_value, check_for_injection

__version__ = "0.1.0"

__all__ = [
    # KV Store
    "kv", "KV", "MemoryKV", "RedisKV",
    # Proxy Pool
    "ProxyPool", "ProxySession",
    # Circuit Breaker
    "CircuitBreaker", "CircuitOpenError",
    # Fingerprinting
    "generate_fingerprint", "get_or_create_fingerprint", "BrowserFingerprint",
    # Rate Limiting
    "acquire_slot", "release_slot", "wait_for_slot",
    # Sanitization
    "sanitize_string", "sanitize_value", "check_for_injection",
]
