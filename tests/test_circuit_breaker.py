"""Tests for the circuit breaker."""

import pytest
from stealth_fetch.kv import MemoryKV
from stealth_fetch.circuit_breaker import CircuitBreaker, CircuitOpenError


@pytest.fixture
def store():
    return MemoryKV()


@pytest.fixture
def breaker(store):
    return CircuitBreaker("test-service", failure_threshold=3, recovery_timeout=2, kv_store=store)


@pytest.mark.asyncio
async def test_closed_on_success(breaker):
    async with breaker:
        pass
    assert breaker.state == "closed"
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_opens_after_threshold(breaker):
    for i in range(3):
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError(f"fail {i}")

    assert breaker.state == "open"


@pytest.mark.asyncio
async def test_open_circuit_raises(breaker):
    # Trip the breaker
    for _ in range(3):
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("fail")

    # Now it should raise CircuitOpenError
    with pytest.raises(CircuitOpenError) as exc_info:
        async with breaker:
            pass

    assert exc_info.value.service == "test-service"
    assert exc_info.value.retry_after > 0


@pytest.mark.asyncio
async def test_reset(breaker):
    for _ in range(3):
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("fail")

    assert breaker.state == "open"
    breaker.reset()
    assert breaker.state == "closed"
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_success_resets_failures(breaker):
    # Two failures (below threshold)
    for _ in range(2):
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("fail")

    assert breaker.failure_count == 2

    # One success resets
    async with breaker:
        pass

    assert breaker.failure_count == 0
    assert breaker.state == "closed"
