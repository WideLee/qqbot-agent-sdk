# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.utils module.

Tests cover:
- build_user_agent() - User-Agent string construction
- get_api_headers() - HTTP headers generation
- coerce_list() - Config value normalization
- parse_qq_timestamp() - Timestamp parsing (ISO 8601 and Unix milliseconds)
- append_block() - Text block concatenation
- entry_matches() - Allowlist matching
- is_fatal_send_error() - Error classification
"""

import platform
import sys
from datetime import datetime, timezone
from unittest.mock import patch


from qqbot_agent_sdk import utils
from qqbot_agent_sdk.utils import (
    append_block,
    build_user_agent,
    coerce_list,
    entry_matches,
    get_api_headers,
    is_fatal_send_error,
    parse_qq_timestamp,
)


# Get QQBOT_VERSION directly
from qqbot_agent_sdk.constants import QQBOT_VERSION


# ── Test build_user_agent ─────────────────────────────────────────────

class TestBuildUserAgent:
    """Test build_user_agent() function."""

    def test_build_user_agent_default(self):
        """Test default User-Agent without extra items."""
        from qqbot_agent_sdk.constants import sdk_config
        
        # Clear extra_ua_items
        original = sdk_config.extra_ua_items
        sdk_config.extra_ua_items = []
        
        try:
            ua = build_user_agent()
            
            # Should contain version
            assert f"QQBotAdapter/{QQBOT_VERSION}" in ua
            
            # Should contain Python version
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            assert f"Python/{py_ver}" in ua
            
            # Should contain OS name
            os_name = platform.system().lower()
            assert os_name in ua
            
            # Format: QQBotAdapter/X.Y.Z (Python/A.B.C; os)
            assert ua.startswith("QQBotAdapter/")
            assert "(" in ua and ")" in ua
        finally:
            sdk_config.extra_ua_items = original

    def test_build_user_agent_with_extra_items(self):
        """Test User-Agent with extra UA items."""
        from qqbot_agent_sdk.constants import sdk_config
        
        original = sdk_config.extra_ua_items
        sdk_config.extra_ua_items = ["Hermes/1.0.0", "CustomApp/2.3.4"]
        
        try:
            ua = build_user_agent()
            
            assert "Hermes/1.0.0" in ua
            assert "CustomApp/2.3.4" in ua
            assert ua.count(";") >= 3  # Python; os; extra1; extra2
        finally:
            sdk_config.extra_ua_items = original

    def test_build_user_agent_format(self):
        """Test User-Agent string format."""
        from qqbot_agent_sdk.constants import sdk_config
        
        original = sdk_config.extra_ua_items
        sdk_config.extra_ua_items = []
        
        try:
            ua = build_user_agent()
            
            # Should match: QQBotAdapter/X.Y.Z (...)
            assert ua.startswith("QQBotAdapter/")
            parts = ua.split(" ", 1)
            assert len(parts) == 2
            assert parts[1].startswith("(")
            assert parts[1].endswith(")")
        finally:
            sdk_config.extra_ua_items = original


# ── Test get_api_headers ──────────────────────────────────────────────

class TestGetApiHeaders:
    """Test get_api_headers() function."""

    def test_get_api_headers_structure(self):
        """Test API headers structure."""
        headers = get_api_headers()
        
        assert "Content-Type" in headers
        assert "Accept" in headers
        assert "User-Agent" in headers

    def test_get_api_headers_values(self):
        """Test API headers values."""
        headers = get_api_headers()
        
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"].startswith("QQBotAdapter/")

    def test_get_api_headers_includes_user_agent(self):
        """Test that headers include dynamic User-Agent."""
        headers = get_api_headers()
        ua = build_user_agent()
        
        assert headers["User-Agent"] == ua


# ── Test coerce_list ──────────────────────────────────────────────────

class TestCoerceList:
    """Test coerce_list() function."""

    def test_coerce_list_none(self):
        """Test None returns empty list."""
        result = coerce_list(None)
        assert result == []

    def test_coerce_list_empty_string(self):
        """Test empty string returns empty list."""
        result = coerce_list("")
        assert result == []

    def test_coerce_list_whitespace_only(self):
        """Test whitespace-only string returns empty list."""
        result = coerce_list("   \t\n   ")
        assert result == []

    def test_coerce_list_single_string(self):
        """Test single string value."""
        result = coerce_list("value1")
        assert result == ["value1"]

    def test_coerce_list_comma_separated(self):
        """Test comma-separated string."""
        result = coerce_list("value1,value2,value3")
        assert result == ["value1", "value2", "value3"]

    def test_coerce_list_comma_separated_with_spaces(self):
        """Test comma-separated string with spaces."""
        result = coerce_list("value1, value2 , value3")
        assert result == ["value1", "value2", "value3"]

    def test_coerce_list_trailing_comma(self):
        """Test comma-separated string with trailing comma."""
        result = coerce_list("value1,value2,")
        assert result == ["value1", "value2"]

    def test_coerce_list_empty_items(self):
        """Test comma-separated with empty items."""
        result = coerce_list("value1,,value2,  ,value3")
        assert result == ["value1", "value2", "value3"]

    def test_coerce_list_from_list(self):
        """Test list input."""
        result = coerce_list(["value1", "value2", "value3"])
        assert result == ["value1", "value2", "value3"]

    def test_coerce_list_from_list_with_spaces(self):
        """Test list with spaces."""
        result = coerce_list(["  value1  ", "value2", "  value3  "])
        assert result == ["value1", "value2", "value3"]

    def test_coerce_list_from_tuple(self):
        """Test tuple input."""
        result = coerce_list(("value1", "value2"))
        assert result == ["value1", "value2"]

    def test_coerce_list_from_set(self):
        """Test set input."""
        result = coerce_list({"value1", "value2"})
        assert len(result) == 2
        assert "value1" in result
        assert "value2" in result

    def test_coerce_list_from_number(self):
        """Test numeric input."""
        result = coerce_list(123)
        assert result == ["123"]

    def test_coerce_list_from_list_with_numbers(self):
        """Test list with numbers."""
        result = coerce_list([1, 2, 3])
        assert result == ["1", "2", "3"]

    def test_coerce_list_filters_empty_strings(self):
        """Test that empty strings are filtered out."""
        result = coerce_list(["value1", "", "value2", "  ", "value3"])
        assert result == ["value1", "value2", "value3"]


# ── Test parse_qq_timestamp ───────────────────────────────────────────

class TestParseQQTimestamp:
    """Test parse_qq_timestamp() function."""

    def test_parse_iso8601_with_timezone(self):
        """Test ISO 8601 timestamp with timezone."""
        ts = "2024-01-15T10:30:00+08:00"
        result = parse_qq_timestamp(ts)
        
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.tzinfo is not None

    def test_parse_iso8601_utc(self):
        """Test ISO 8601 timestamp in UTC."""
        ts = "2024-01-15T10:30:00+00:00"
        result = parse_qq_timestamp(ts)
        
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.tzinfo is not None

    def test_parse_unix_milliseconds(self):
        """Test Unix millisecond timestamp."""
        # 2024-01-15 10:30:00 UTC = 1705318200000 ms
        ts = "1705318200000"
        result = parse_qq_timestamp(ts)
        
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_parse_unix_milliseconds_as_int(self):
        """Test Unix millisecond timestamp conversion."""
        ts = "1705318200000"
        result = parse_qq_timestamp(ts)
        
        # Should be around Jan 15, 2024
        assert result.year == 2024
        assert result.month == 1

    def test_parse_empty_string(self):
        """Test empty string returns current time and logs warning."""

        with patch.object(utils.logger, "warning") as mock_warn:
            result = parse_qq_timestamp("")

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        # Should be recent
        now = datetime.now(tz=timezone.utc)
        assert abs((now - result).total_seconds()) < 5
        mock_warn.assert_called_once()
        assert "empty input" in mock_warn.call_args[0][0]

    def test_parse_invalid_string(self):
        """Test invalid string returns current time and logs warning."""
        with patch.object(utils.logger, "warning") as mock_warn:
            result = parse_qq_timestamp("invalid_timestamp")

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        mock_warn.assert_called_once()
        assert "failed to parse" in mock_warn.call_args[0][0]

    def test_parse_none(self):
        """Test None returns current time and logs warning."""
        with patch.object(utils.logger, "warning") as mock_warn:
            result = parse_qq_timestamp(None)  # type: ignore

        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        mock_warn.assert_called_once()
        assert "empty input" in mock_warn.call_args[0][0]


# ── Test append_block ─────────────────────────────────────────────────

class TestAppendBlock:
    """Test append_block() function."""

    def test_append_block_basic(self):
        """Test basic block appending."""
        result = append_block("Hello", "World")
        assert result == "Hello\n\nWorld"

    def test_append_block_empty_base(self):
        """Test appending to empty base."""
        result = append_block("", "Block")
        assert result == "Block"

    def test_append_block_whitespace_base(self):
        """Test appending to whitespace-only base."""
        result = append_block("   \n\t   ", "Block")
        assert result == "Block"

    def test_append_block_strips_result(self):
        """Test result is stripped."""
        result = append_block("  Hello  ", "  World  ")
        assert result == "Hello  \n\n  World"

    def test_append_block_multiline(self):
        """Test appending multiline blocks."""
        base = "Line 1\nLine 2"
        block = "Line 3\nLine 4"
        result = append_block(base, block)
        assert result == "Line 1\nLine 2\n\nLine 3\nLine 4"

    def test_append_block_preserves_internal_newlines(self):
        """Test internal newlines are preserved."""
        result = append_block("Hello\nWorld", "Foo\nBar")
        assert result == "Hello\nWorld\n\nFoo\nBar"

    def test_append_block_both_empty(self):
        """Test both base and block empty."""
        result = append_block("", "")
        assert result == ""


# ── Test entry_matches ────────────────────────────────────────────────

class TestEntryMatches:
    """Test entry_matches() function."""

    def test_entry_matches_wildcard(self):
        """Test wildcard matches everything."""
        assert entry_matches(["*"], "any_value") is True
        assert entry_matches(["*"], "another_value") is True
        assert entry_matches(["*"], "") is True

    def test_entry_matches_exact(self):
        """Test exact match."""
        assert entry_matches(["abc123"], "abc123") is True

    def test_entry_matches_case_insensitive(self):
        """Test case-insensitive matching."""
        assert entry_matches(["abc123"], "ABC123") is True
        assert entry_matches(["ABC123"], "abc123") is True
        assert entry_matches(["AbC123"], "aBc123") is True

    def test_entry_matches_multiple_entries(self):
        """Test matching with multiple entries."""
        entries = ["user1", "user2", "user3"]
        assert entry_matches(entries, "user1") is True
        assert entry_matches(entries, "user2") is True
        assert entry_matches(entries, "user3") is True
        assert entry_matches(entries, "user4") is False

    def test_entry_matches_with_whitespace(self):
        """Test matching with whitespace."""
        assert entry_matches(["  abc123  "], "abc123") is True
        assert entry_matches(["abc123"], "  abc123  ") is True

    def test_entry_matches_no_match(self):
        """Test no match."""
        assert entry_matches(["abc123"], "xyz999") is False

    def test_entry_matches_empty_list(self):
        """Test empty entry list."""
        assert entry_matches([], "any_value") is False

    def test_entry_matches_empty_target(self):
        """Test empty target."""
        assert entry_matches(["abc123"], "") is False
        assert entry_matches(["*"], "") is True  # Wildcard matches empty

    def test_entry_matches_numeric_values(self):
        """Test numeric values."""
        assert entry_matches([123], "123") is True
        assert entry_matches(["123"], 123) is True

    def test_entry_matches_wildcard_in_list(self):
        """Test wildcard in mixed list."""
        entries = ["user1", "*", "user2"]
        assert entry_matches(entries, "any_user") is True


# ── Test is_fatal_send_error ──────────────────────────────────────────

class TestIsFatalSendError:
    """Test is_fatal_send_error() function."""

    def test_is_fatal_invalid(self):
        """Test 'invalid' keyword."""
        assert is_fatal_send_error("Invalid request") is True
        assert is_fatal_send_error("invalid token") is True
        assert is_fatal_send_error("Request is INVALID") is True

    def test_is_fatal_forbidden(self):
        """Test 'forbidden' keyword."""
        assert is_fatal_send_error("403 Forbidden") is True
        assert is_fatal_send_error("Access forbidden") is True
        assert is_fatal_send_error("FORBIDDEN") is True

    def test_is_fatal_not_found(self):
        """Test 'not found' keyword."""
        assert is_fatal_send_error("404 Not Found") is True
        assert is_fatal_send_error("Resource not found") is True
        assert is_fatal_send_error("NOT FOUND") is True

    def test_is_fatal_bad_request(self):
        """Test 'bad request' keyword."""
        assert is_fatal_send_error("400 Bad Request") is True
        assert is_fatal_send_error("bad request format") is True
        assert is_fatal_send_error("BAD REQUEST") is True

    def test_is_not_fatal_timeout(self):
        """Test timeout is not fatal."""
        assert is_fatal_send_error("Request timeout") is False
        assert is_fatal_send_error("Connection timed out") is False

    def test_is_not_fatal_server_error(self):
        """Test server errors are not fatal."""
        assert is_fatal_send_error("500 Internal Server Error") is False
        assert is_fatal_send_error("503 Service Unavailable") is False

    def test_is_not_fatal_network_error(self):
        """Test network errors are not fatal."""
        assert is_fatal_send_error("Connection refused") is False
        assert is_fatal_send_error("Network unreachable") is False

    def test_is_fatal_case_insensitive(self):
        """Test case-insensitive matching."""
        assert is_fatal_send_error("INVALID REQUEST") is True
        assert is_fatal_send_error("Forbidden Access") is True
        assert is_fatal_send_error("not FOUND") is True

    def test_is_fatal_partial_match(self):
        """Test partial keyword matching."""
        assert is_fatal_send_error("Error: invalid parameter") is True
        assert is_fatal_send_error("The request is forbidden by policy") is True

    def test_is_not_fatal_empty_string(self):
        """Test empty string is not fatal."""
        assert is_fatal_send_error("") is False

    def test_is_not_fatal_unrelated_error(self):
        """Test unrelated errors are not fatal."""
        assert is_fatal_send_error("Something went wrong") is False
        assert is_fatal_send_error("Unknown error") is False


# ── Test Integration ──────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for utils functions."""

    def test_headers_include_valid_user_agent(self):
        """Test that get_api_headers includes valid User-Agent."""
        headers = get_api_headers()
        ua = headers["User-Agent"]
        
        # Should be valid format
        assert ua.startswith("QQBotAdapter/")
        assert "Python/" in ua
        assert "(" in ua and ")" in ua

    def test_coerce_list_with_entry_matches(self):
        """Test coerce_list output works with entry_matches."""
        raw_config = "user1, user2, user3"
        entries = coerce_list(raw_config)
        
        assert entry_matches(entries, "user1") is True
        assert entry_matches(entries, "user2") is True
        assert entry_matches(entries, "user4") is False

    def test_timestamp_parsing_real_data(self):
        """Test timestamp parsing with realistic data."""
        # ISO 8601 from QQ Bot
        iso_ts = "2026-04-27T17:44:00+08:00"
        result1 = parse_qq_timestamp(iso_ts)
        assert result1.year == 2026
        
        # Unix milliseconds from QQ Bot
        unix_ts = "1714212240000"  # 2024-04-27 17:44:00 UTC
        result2 = parse_qq_timestamp(unix_ts)
        assert result2.year == 2024

    def test_append_block_realistic_usage(self):
        """Test append_block with realistic message content."""
        base = "User said: Hello"
        attachments = "[Voice] audio.silk\n[Image] photo.jpg"
        
        result = append_block(base, attachments)
        
        assert "User said: Hello" in result
        assert "[Voice] audio.silk" in result
        assert "[Image] photo.jpg" in result
        assert "\n\n" in result  # Double newline separator
