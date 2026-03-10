"""Request body sanitization utilities.

Strips HTML tags, null bytes, control characters, and script injection patterns
from string values. Works recursively on dicts and lists.

Usage:
    from stealth_fetch import sanitize_value, check_for_injection

    clean = sanitize_value({"name": "<script>alert('xss')</script>Ben"})
    # {"name": "alert('xss')Ben"}

    is_suspicious = check_for_injection(user_input)
"""

import re
from typing import Any

# Matches HTML tags (including self-closing and attributes)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Matches null bytes and ASCII control chars (except newline, tab, carriage return)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Matches common script injection patterns
_SCRIPT_RE = re.compile(
    r"(javascript\s*:|on\w+\s*=|<script|<\/script|eval\s*\(|document\.(cookie|location))",
    re.IGNORECASE,
)


def sanitize_string(value: str) -> str:
    """Sanitize a single string value.

    Removes control characters and HTML tags, then strips whitespace.
    """
    value = _CONTROL_CHAR_RE.sub("", value)
    value = _HTML_TAG_RE.sub("", value)
    return value.strip()


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize values in a data structure.

    Handles str, dict, and list. Other types pass through unchanged.
    """
    if isinstance(value, str):
        return sanitize_string(value)
    if isinstance(value, dict):
        return {k: sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def has_script_injection(value: str) -> bool:
    """Check if a string contains potential script injection patterns."""
    return bool(_SCRIPT_RE.search(value))


def check_for_injection(data: Any) -> bool:
    """Recursively check a data structure for injection attempts.

    Returns True if any string value contains suspicious patterns.
    """
    if isinstance(data, str):
        return has_script_injection(data)
    if isinstance(data, dict):
        return any(check_for_injection(v) for v in data.values())
    if isinstance(data, list):
        return any(check_for_injection(item) for item in data)
    return False
