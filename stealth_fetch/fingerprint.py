"""Per-session browser fingerprint generator.

Each session gets a unique, consistent browser identity (Chrome version + OS +
matching headers). Prevents all users from sharing the same User-Agent and
sec-ch-ua headers — a dead giveaway for bot traffic.

Fingerprints are persisted in the KV store so a session keeps the same identity
across multiple requests.

Usage:
    from stealth_fetch import generate_fingerprint, get_or_create_fingerprint

    # One-off random fingerprint
    fp = generate_fingerprint()
    print(fp.user_agent)
    print(fp.to_headers())

    # Persistent fingerprint (same identity for same key)
    fp = get_or_create_fingerprint("session:user-42")
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, asdict

from .kv import kv as _default_kv, KV

logger = logging.getLogger("stealth_fetch.fingerprint")

# -- Detect supported curl_cffi impersonate targets at import time -----------
_SUPPORTED_TARGETS: set[str] = set()
_curl_available = False

try:
    from curl_cffi.requests import BrowserType
    _SUPPORTED_TARGETS = {bt.value for bt in BrowserType}
    _curl_available = True
except Exception:
    pass

if not _SUPPORTED_TARGETS:
    # Fallback: conservative list known to work in curl_cffi 0.7+
    _SUPPORTED_TARGETS = {
        "chrome99", "chrome100", "chrome101", "chrome104", "chrome107",
        "chrome110", "chrome116", "chrome119", "chrome120", "chrome123",
        "chrome124",
    }

# -- Select best impersonate target ------------------------------------------
_PREFERRED_TARGETS = [
    "chrome136", "chrome133a", "chrome131", "chrome124",
    "chrome123", "chrome120",
]

_BEST_TARGET = "chrome"
for _t in _PREFERRED_TARGETS:
    if _t in _SUPPORTED_TARGETS:
        _BEST_TARGET = _t
        break

# -- OS profiles --------------------------------------------------------------
_OS_PROFILES = [
    {
        "os_name": "macOS",
        "ua_fragment": "(Macintosh; Intel Mac OS X 10_15_7)",
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "os_name": "macOS",
        "ua_fragment": "(Macintosh; Intel Mac OS X 14_0)",
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "os_name": "Windows",
        "ua_fragment": "(Windows NT 10.0; Win64; x64)",
        "sec_ch_ua_platform": '"Windows"',
    },
]

_CHROME_MIN = 120
_CHROME_MAX = 136


@dataclass
class BrowserFingerprint:
    """Immutable browser identity for a session."""

    chrome_version: int
    os_name: str
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_platform: str
    curl_impersonate: str

    def to_headers(self) -> dict[str, str]:
        """Return header overrides for this fingerprint."""
        return {
            "user-agent": self.user_agent,
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-platform": self.sec_ch_ua_platform,
        }


def generate_fingerprint() -> BrowserFingerprint:
    """Generate a random browser fingerprint.

    Returns a new BrowserFingerprint with randomized Chrome version and OS.
    The curl_impersonate target is set to the best available version.
    """
    chrome_ver = random.randint(_CHROME_MIN, _CHROME_MAX)
    os_profile = random.choice(_OS_PROFILES)

    user_agent = (
        f"Mozilla/5.0 {os_profile['ua_fragment']} "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_ver}.0.0.0 Safari/537.36"
    )

    sec_ch_ua = (
        f'"Not:A-Brand";v="99", "Google Chrome";v="{chrome_ver}", '
        f'"Chromium";v="{chrome_ver}"'
    )

    return BrowserFingerprint(
        chrome_version=chrome_ver,
        os_name=os_profile["os_name"],
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        sec_ch_ua_platform=os_profile["sec_ch_ua_platform"],
        curl_impersonate=_BEST_TARGET,
    )


def get_or_create_fingerprint(
    fingerprint_id: str,
    kv_store: KV | None = None,
) -> BrowserFingerprint:
    """Load fingerprint from KV store, or generate and persist a new one.

    Args:
        fingerprint_id: Unique key for this fingerprint (e.g. "session:user-42").
        kv_store: Optional KV store. Defaults to module KV.

    Returns:
        BrowserFingerprint with consistent identity for this session.
    """
    store = kv_store or _default_kv
    redis_key = f"fp:{fingerprint_id}"
    raw = store.get(redis_key)

    if raw:
        data = json.loads(raw)
        cached_target = data.get("curl_impersonate", "")
        if cached_target not in _SUPPORTED_TARGETS:
            logger.info("Invalidating cached fingerprint %s (unsupported target)", redis_key)
            store.delete(redis_key)
        else:
            return BrowserFingerprint(**data)

    fp = generate_fingerprint()
    store.set(redis_key, json.dumps(asdict(fp)))
    return fp
