# -*- coding: utf-8 -*-
"""Shared utilities — User-Agent, HTTP headers, config coercion.

All functions are stateless and have no external framework dependencies.
"""

from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from .constants import QQBOT_VERSION

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------

def build_user_agent() -> str:
    """Build a descriptive User-Agent string for outgoing HTTP requests.

    Format (without extra_ua_items)::

        QQBotAdapter/<sdk_version> (Python/<py_version>; <os>)

    Format (with extra_ua_items set via :func:`~qqbot_agent_sdk.configure`)::

        QQBotAdapter/<sdk_version> (Python/<py_version>; <os>; <item1>; <item2>; ...)

    Example::

        QQBotAdapter/<sdk_version> (Python/3.11.9; darwin; MyApp/1.0.0)
    """
    from .constants import sdk_config  # local import to avoid circular dep

    py_ver = (
        f"{sys.version_info.major}"
        f".{sys.version_info.minor}"
        f".{sys.version_info.micro}"
    )
    os_name = platform.system().lower()
    
    # Base parentheses content: Python version and OS
    base_info = f"Python/{py_ver}; {os_name}"
    
    # Append extra items if configured
    if sdk_config.extra_ua_items:
        extra = "; ".join(sdk_config.extra_ua_items)
        parentheses = f"{base_info}; {extra}"
    else:
        parentheses = base_info
    
    return f"QQBotAdapter/{QQBOT_VERSION} ({parentheses})"


def get_api_headers() -> Dict[str, str]:
    """Return standard HTTP headers for QQBot API requests.

    ``q.qq.com`` requires ``Accept: application/json``; without it the server
    returns a JavaScript anti-bot challenge page.
    """
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": build_user_agent(),
    }


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def coerce_list(value: Any) -> List[str]:
    """Coerce a config value into a trimmed, non-empty string list.

    Accepts comma-separated strings, lists, tuples, sets, or single values.

    :param value: Raw config value (any type).
    :returns: List of non-empty stripped strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    stripped = str(value).strip()
    return [stripped] if stripped else []


# ---------------------------------------------------------------------------
# QQ timestamp parsing
# ---------------------------------------------------------------------------

def parse_qq_timestamp(raw: str) -> datetime:
    """Parse a QQ Bot timestamp string into a timezone-aware :class:`datetime`.

    QQ Bot returns timestamps in two formats depending on the event type:

    - ISO 8601 string: ``"2024-01-15T10:30:00+08:00"``
    - Millisecond Unix timestamp string: ``"1705283400000"``

    Falls back to :func:`datetime.now` (UTC) if parsing fails.

    :param raw: Raw timestamp string from a QQ Bot event payload.
    :returns: Timezone-aware :class:`~datetime.datetime` in UTC or local tz.
    """
    if not raw:
        logger.warning("parse_qq_timestamp: empty input, falling back to now()")
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    logger.warning("parse_qq_timestamp: failed to parse %r, falling back to now()", raw)
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def append_block(base: str, block: str) -> str:
    """Append *block* to *base* with a double-newline separator.

    If *base* is empty or whitespace-only, returns *block* directly.

    :param base: Existing text body (may be empty).
    :param block: Text block to append.
    :returns: Combined string, stripped of leading/trailing whitespace.

    Example::

        >>> append_block("Hello", "[Voice] transcript")
        'Hello\\n\\n[Voice] transcript'
        >>> append_block("", "[image: photo.jpg]")
        '[image: photo.jpg]'
    """
    if base.strip():
        return (base + "\n\n" + block).strip()
    return block


# ---------------------------------------------------------------------------
# ACL helpers
# ---------------------------------------------------------------------------

def entry_matches(entries: List[str], target: str) -> bool:
    """Return ``True`` if *target* matches any entry in an allowlist.

    Comparison is case-insensitive.  An entry of ``"*"`` matches everything.

    :param entries: List of allowed values (may include ``"*"``).
    :param target: The value to check (e.g. user openid or group openid).
    :returns: ``True`` if *target* is permitted.

    Example::

        >>> entry_matches(["*"], "any_openid")
        True
        >>> entry_matches(["abc123"], "ABC123")
        True
        >>> entry_matches(["abc123"], "xyz999")
        False
    """
    normalized = str(target).strip().lower()
    for entry in entries:
        e = str(entry).strip().lower()
        if e in ("*", normalized):
            return True
    return False


# ---------------------------------------------------------------------------
# Send-error classification
# ---------------------------------------------------------------------------

_FATAL_SEND_KEYWORDS = ("invalid", "forbidden", "not found", "bad request")


def is_fatal_send_error(error_msg: str) -> bool:
    """Return ``True`` if *error_msg* indicates a non-retryable QQ API error.

    Fatal errors are those where retrying the same request will never succeed
    (e.g. permission denied, resource not found, malformed request).  Network
    timeouts and 5xx server errors are **not** fatal and should be retried.

    :param error_msg: The error message string (from an exception or API body).
    :returns: ``True`` when the error is permanent / non-retryable.
    """
    lower = error_msg.lower()
    return any(k in lower for k in _FATAL_SEND_KEYWORDS)
