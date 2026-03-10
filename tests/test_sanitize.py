"""Tests for sanitization utilities."""

from stealth_fetch.sanitize import (
    sanitize_string,
    sanitize_value,
    has_script_injection,
    check_for_injection,
)


def test_strips_html_tags():
    assert sanitize_string("<b>hello</b>") == "hello"
    assert sanitize_string('<a href="x">click</a>') == "click"


def test_strips_control_chars():
    assert sanitize_string("hello\x00world") == "helloworld"
    assert sanitize_string("test\x07bell") == "testbell"


def test_preserves_newlines_tabs():
    assert sanitize_string("line1\nline2\ttab") == "line1\nline2\ttab"


def test_sanitize_dict():
    result = sanitize_value({"name": "<b>Ben</b>", "age": 30})
    assert result == {"name": "Ben", "age": 30}


def test_sanitize_list():
    result = sanitize_value(["<script>x</script>", "clean"])
    assert result == ["x", "clean"]


def test_sanitize_nested():
    result = sanitize_value({"users": [{"name": "<i>Alice</i>"}]})
    assert result == {"users": [{"name": "Alice"}]}


def test_detects_script_injection():
    assert has_script_injection("javascript:alert(1)") is True
    assert has_script_injection("onclick=steal()") is True
    assert has_script_injection("<script>evil</script>") is True
    assert has_script_injection("eval(code)") is True
    assert has_script_injection("document.cookie") is True


def test_clean_string_not_flagged():
    assert has_script_injection("Hello, world!") is False
    assert has_script_injection("user@example.com") is False


def test_check_for_injection_recursive():
    assert check_for_injection({"x": "javascript:void(0)"}) is True
    assert check_for_injection({"x": [{"y": "eval(z)"}]}) is True
    assert check_for_injection({"x": "safe value"}) is False
