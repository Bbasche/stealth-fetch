"""Circuit breaker pattern for external API calls.

Prevents cascading failures when external services are down or blocking you.
After N consecutive failures, the circuit opens and rejects calls immediately.
After a cooldown period, one test call is allowed to check recovery.

States:
    CLOSED  -> Normal operation, calls go through
    OPEN    -> Service is down, calls fail fast (raises CircuitOpenError)
    HALF_OPEN -> After cooldown, one test call is allowed

Usage:
    from stealth_fetch import CircuitBreaker

    breaker = CircuitBreaker("target-api", failure_threshold=3, recovery_timeout=300)

    async with breaker:
        response = await httpx.get("https://target-api.com/endpoint")

    # Per-session breakers (e.g. one per proxy IP):
    breaker = CircuitBreaker("api:proxy:abc123", failure_threshold=3, recovery_timeout=300)
"""

import logging
import time
from typing import Optional

from .kv import kv as _default_kv, KV

logger = logging.getLogger("stealth_fetch.circuit_breaker")


class CircuitOpenError(Exception):
    """Raised when the circuit is open and the call is rejected."""

    def __init__(self, service: str, retry_after: float):
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"Circuit open for '{service}'. Retry after {retry_after:.0f}s")


class CircuitBreaker:
    """Async context manager implementing the circuit breaker pattern.

    Args:
        service: Name of the service (used as key prefix for state storage).
        failure_threshold: Number of consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait before allowing a test call (half-open).
        kv_store: Optional KV store for shared state. Defaults to module KV.
    """

    def __init__(
        self,
        service: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        kv_store: KV | None = None,
    ):
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._kv = kv_store or _default_kv
        self._key_failures = f"cb:{service}:failures"
        self._key_opened_at = f"cb:{service}:opened_at"
        self._key_state = f"cb:{service}:state"

    @property
    def state(self) -> str:
        """Current circuit state: 'closed', 'open', or 'half_open'."""
        s = self._kv.get(self._key_state)
        return s or "closed"

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        v = self._kv.get(self._key_failures)
        return int(v) if v else 0

    def _is_recovery_due(self) -> bool:
        opened_at = self._kv.get(self._key_opened_at)
        if not opened_at:
            return True
        return (time.time() - float(opened_at)) >= self.recovery_timeout

    async def __aenter__(self):
        current = self.state
        if current == "open":
            if self._is_recovery_due():
                self._kv.set(self._key_state, "half_open")
                logger.info("[CB] %s: half-open, testing recovery", self.service)
            else:
                retry_after = self.recovery_timeout - (
                    time.time() - float(self._kv.get(self._key_opened_at) or 0)
                )
                raise CircuitOpenError(self.service, max(0, retry_after))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Success — reset to closed
            if self.state in ("half_open", "open"):
                logger.info("[CB] %s: recovered, circuit closed", self.service)
            self._kv.set(self._key_state, "closed")
            self._kv.set(self._key_failures, "0")
            return False

        # Failure
        failures = self.failure_count + 1
        self._kv.set(self._key_failures, str(failures))
        logger.warning("[CB] %s: failure #%d (%s)", self.service, failures, exc_val)

        if self.state == "half_open" or failures >= self.failure_threshold:
            self._kv.set(self._key_state, "open")
            self._kv.set(self._key_opened_at, str(time.time()))
            logger.error(
                "[CB] %s: circuit OPEN after %d failures, retry in %ds",
                self.service, failures, self.recovery_timeout,
            )

        return False  # Don't suppress the exception

    def reset(self):
        """Manually reset the circuit breaker to closed state."""
        self._kv.delete(self._key_state)
        self._kv.delete(self._key_failures)
        self._kv.delete(self._key_opened_at)
        logger.info("[CB] %s: manually reset", self.service)
