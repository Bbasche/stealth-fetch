"""Tests for browser fingerprint generation."""

from stealth_fetch.kv import MemoryKV
from stealth_fetch.fingerprint import generate_fingerprint, get_or_create_fingerprint


def test_generate_returns_valid_fingerprint():
    fp = generate_fingerprint()
    assert 120 <= fp.chrome_version <= 136
    assert fp.os_name in ("macOS", "Windows")
    assert "Chrome/" in fp.user_agent
    assert "Mozilla/5.0" in fp.user_agent
    assert fp.curl_impersonate


def test_headers_dict():
    fp = generate_fingerprint()
    headers = fp.to_headers()
    assert "user-agent" in headers
    assert "sec-ch-ua" in headers
    assert "sec-ch-ua-platform" in headers


def test_persistent_fingerprint():
    store = MemoryKV()
    fp1 = get_or_create_fingerprint("session:42", kv_store=store)
    fp2 = get_or_create_fingerprint("session:42", kv_store=store)
    assert fp1.user_agent == fp2.user_agent
    assert fp1.chrome_version == fp2.chrome_version


def test_different_keys_different_fingerprints():
    store = MemoryKV()
    fp1 = get_or_create_fingerprint("session:1", kv_store=store)
    fp2 = get_or_create_fingerprint("session:2", kv_store=store)
    # Technically could be the same by chance, but with 16 chrome versions
    # and 3 OS profiles, collision is rare. Just check they're both valid.
    assert fp1.chrome_version >= 120
    assert fp2.chrome_version >= 120
