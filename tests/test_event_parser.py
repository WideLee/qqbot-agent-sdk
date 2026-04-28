# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.event_parser module.

Tests cover:
- EventParser.parse() - main parsing logic for different event types
- _parse_c2c() - C2C message parsing
- _parse_group() - Group message parsing (with @ mention stripping)
- _parse_guild() - Guild message parsing
- _parse_dm() - Direct message parsing
- _strip_at_mention() - @ mention removal
- InboundEvent dataclass
"""

from typing import Any, Dict


from qqbot_agent_sdk.dto import EventType, MessageAttachment, MsgElement
from qqbot_agent_sdk.event_parser import EventParser, InboundEvent, _strip_at_mention


# ── Test Data Helpers ─────────────────────────────────────────────────

def make_c2c_raw(
    user_openid: str = "USER_OPENID_123",
    content: str = "Hello bot",
    message_id: str = "msg_001",
    timestamp: str = "2026-04-27T10:00:00Z",
) -> Dict[str, Any]:
    """Create a raw C2C_MESSAGE_CREATE payload."""
    return {
        "id": message_id,
        "content": content,
        "timestamp": timestamp,
        "author": {
            "user_openid": user_openid,
        },
    }


def make_group_raw(
    group_openid: str = "GROUP_OPENID_456",
    member_openid: str = "MEMBER_OPENID_789",
    content: str = "@Bot hello",
    message_id: str = "msg_002",
    timestamp: str = "2026-04-27T10:01:00Z",
) -> Dict[str, Any]:
    """Create a raw GROUP_AT_MESSAGE_CREATE payload."""
    return {
        "id": message_id,
        "group_openid": group_openid,
        "content": content,
        "timestamp": timestamp,
        "author": {
            "member_openid": member_openid,
        },
    }


def make_guild_raw(
    channel_id: str = "CHANNEL_123",
    user_id: str = "USER_456",
    username: str = "Alice",
    nick: str = "AliceNick",
    content: str = "Guild message",
    message_id: str = "msg_003",
    timestamp: str = "2026-04-27T10:02:00Z",
) -> Dict[str, Any]:
    """Create a raw GUILD_MESSAGE_CREATE payload."""
    return {
        "id": message_id,
        "channel_id": channel_id,
        "content": content,
        "timestamp": timestamp,
        "author": {
            "id": user_id,
            "username": username,
        },
        "member": {
            "nick": nick,
        },
    }


def make_dm_raw(
    guild_id: str = "GUILD_789",
    user_id: str = "USER_111",
    content: str = "DM message",
    message_id: str = "msg_004",
    timestamp: str = "2026-04-27T10:03:00Z",
) -> Dict[str, Any]:
    """Create a raw DIRECT_MESSAGE_CREATE payload."""
    return {
        "id": message_id,
        "guild_id": guild_id,
        "content": content,
        "timestamp": timestamp,
        "author": {
            "id": user_id,
        },
    }


# ── Test _strip_at_mention ────────────────────────────────────────────

class TestStripAtMention:
    """Test _strip_at_mention() helper function."""

    def test_strip_at_mention_basic(self):
        """Test stripping basic @mention."""
        result = _strip_at_mention("@Bot hello world")
        assert result == "hello world"

    def test_strip_at_mention_with_whitespace(self):
        """Test stripping @mention with extra whitespace."""
        result = _strip_at_mention("@Bot   hello")
        assert result == "hello"

    def test_strip_at_mention_no_space(self):
        """Test stripping @mention without space after name."""
        result = _strip_at_mention("@Bothello")
        assert result == ""

    def test_strip_at_mention_multiple_words(self):
        """Test that only leading @mention is stripped."""
        result = _strip_at_mention("@Bot hello @someone else")
        assert result == "hello @someone else"

    def test_strip_at_mention_no_mention(self):
        """Test content without @mention."""
        result = _strip_at_mention("hello world")
        assert result == "hello world"

    def test_strip_at_mention_empty(self):
        """Test empty string."""
        result = _strip_at_mention("")
        assert result == ""

    def test_strip_at_mention_only_mention(self):
        """Test string with only @mention."""
        result = _strip_at_mention("@Bot")
        assert result == ""


# ── Test InboundEvent Dataclass ───────────────────────────────────────

class TestInboundEvent:
    """Test InboundEvent dataclass."""

    def test_inbound_event_creation(self):
        """Test creating InboundEvent with required fields."""
        event = InboundEvent(
            event_type="C2C_MESSAGE_CREATE",
            chat_id="user_123",
            user_id="user_123",
            chat_scope="c2c",
            content="Hello",
            message_id="msg_001",
            timestamp="2026-04-27T10:00:00Z",
            message_type=0,
        )
        
        assert event.event_type == "C2C_MESSAGE_CREATE"
        assert event.chat_id == "user_123"
        assert event.user_id == "user_123"
        assert event.chat_scope == "c2c"
        assert event.content == "Hello"
        assert event.message_id == "msg_001"
        assert event.attachments == []
        assert event.msg_elements == []
        assert event.user_name is None
        assert event.raw is None

    def test_inbound_event_with_optional_fields(self):
        """Test InboundEvent with optional fields."""
        attachment = MessageAttachment(url="https://example.com/file.jpg")
        msg_elem = MsgElement(msg_idx="0", content="quoted")
        
        event = InboundEvent(
            event_type="GUILD_MESSAGE_CREATE",
            chat_id="channel_123",
            user_id="user_456",
            chat_scope="guild",
            content="Message",
            message_id="msg_003",
            timestamp="2026-04-27T10:02:00Z",
            message_type=0,
            attachments=[attachment],
            msg_elements=[msg_elem],
            user_name="Alice",
            raw={"test": "data"},
        )
        
        assert len(event.attachments) == 1
        assert len(event.msg_elements) == 1
        assert event.user_name == "Alice"
        assert event.raw == {"test": "data"}


# ── Test EventParser.parse() ──────────────────────────────────────────

class TestEventParserParse:
    """Test EventParser.parse() main entry point."""

    def test_parse_invalid_raw_type(self):
        """Test parse() returns None for non-dict raw data."""
        result = EventParser.parse("C2C_MESSAGE_CREATE", "invalid")  # type: ignore
        assert result is None
        
        result = EventParser.parse("C2C_MESSAGE_CREATE", None)  # type: ignore
        assert result is None

    def test_parse_unsupported_event_type(self):
        """Test parse() returns None for unsupported event type."""
        raw = make_c2c_raw()
        result = EventParser.parse("UNKNOWN_EVENT_TYPE", raw)
        assert result is None

    def test_parse_ready_event(self):
        """Test parse() returns None for READY event (not supported)."""
        raw = {"version": 1, "session_id": "session_123"}
        result = EventParser.parse(EventType.READY, raw)
        assert result is None

    def test_parse_interaction_create(self):
        """Test parse() returns None for INTERACTION_CREATE (not a message event)."""
        raw = {"id": "interaction_123", "data": {}}
        result = EventParser.parse(EventType.INTERACTION_CREATE, raw)
        assert result is None


# ── Test C2C Message Parsing ──────────────────────────────────────────

class TestParseC2C:
    """Test C2C_MESSAGE_CREATE parsing."""

    def test_parse_c2c_success(self):
        """Test successful C2C message parsing."""
        raw = make_c2c_raw(
            user_openid="USER_123",
            content="Hello bot",
            message_id="msg_001",
            timestamp="2026-04-27T10:00:00Z",
        )
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.event_type == EventType.C2C_MESSAGE_CREATE
        assert event.chat_id == "USER_123"
        assert event.user_id == "USER_123"
        assert event.chat_scope == "c2c"
        assert event.content == "Hello bot"
        assert event.message_id == "msg_001"
        assert event.timestamp == "2026-04-27T10:00:00Z"
        assert event.message_type == 0
        assert event.raw == raw

    def test_parse_c2c_with_attachments(self):
        """Test C2C message with attachments."""
        raw = make_c2c_raw()
        raw["attachments"] = [
            {"url": "https://example.com/image.jpg", "content_type": "image/jpeg"}
        ]
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert len(event.attachments) == 1
        assert event.attachments[0].url == "https://example.com/image.jpg"

    def test_parse_c2c_missing_user_openid(self):
        """Test C2C message without user_openid returns None."""
        raw = {
            "id": "msg_001",
            "content": "Hello",
            "timestamp": "2026-04-27T10:00:00Z",
            "author": {},  # Missing user_openid
        }
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        assert event is None

    def test_parse_c2c_strips_whitespace(self):
        """Test C2C content whitespace stripping."""
        raw = make_c2c_raw(content="  Hello bot  \n")
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "Hello bot"


# ── Test Group Message Parsing ────────────────────────────────────────

class TestParseGroup:
    """Test GROUP_AT_MESSAGE_CREATE parsing."""

    def test_parse_group_success(self):
        """Test successful group message parsing."""
        raw = make_group_raw(
            group_openid="GROUP_456",
            member_openid="MEMBER_789",
            content="@Bot hello",
            message_id="msg_002",
            timestamp="2026-04-27T10:01:00Z",
        )
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.event_type == EventType.GROUP_AT_MESSAGE_CREATE
        assert event.chat_id == "GROUP_456"
        assert event.user_id == "MEMBER_789"
        assert event.chat_scope == "group"
        assert event.content == "hello"  # @Bot stripped
        assert event.message_id == "msg_002"
        assert event.timestamp == "2026-04-27T10:01:00Z"

    def test_parse_group_strips_at_mention(self):
        """Test group message strips @mention."""
        raw = make_group_raw(content="@Bot please help me")
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "please help me"

    def test_parse_group_at_mention_with_whitespace(self):
        """Test @mention stripping with extra whitespace."""
        raw = make_group_raw(content="@Bot   do something")
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "do something"

    def test_parse_group_missing_group_openid(self):
        """Test group message without group_openid returns None."""
        raw = {
            "id": "msg_002",
            "content": "@Bot hello",
            "timestamp": "2026-04-27T10:01:00Z",
            "author": {"member_openid": "MEMBER_789"},
            # Missing group_openid
        }
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        assert event is None

    def test_parse_group_with_msg_elements(self):
        """Test group message with msg_elements (quoted message)."""
        raw = make_group_raw()
        raw["msg_elements"] = [
            {
                "msg_idx": "0",
                "content": "original message",
            }
        ]
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert len(event.msg_elements) == 1
        assert event.msg_elements[0].content == "original message"


# ── Test Guild Message Parsing ────────────────────────────────────────

class TestParseGuild:
    """Test GUILD_MESSAGE_CREATE and GUILD_AT_MESSAGE_CREATE parsing."""

    def test_parse_guild_message_create(self):
        """Test GUILD_MESSAGE_CREATE parsing."""
        raw = make_guild_raw(
            channel_id="CHANNEL_123",
            user_id="USER_456",
            username="Alice",
            nick="AliceNick",
            content="Guild message",
            message_id="msg_003",
            timestamp="2026-04-27T10:02:00Z",
        )
        
        event = EventParser.parse(EventType.GUILD_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.event_type == EventType.GUILD_MESSAGE_CREATE
        assert event.chat_id == "CHANNEL_123"
        assert event.user_id == "USER_456"
        assert event.chat_scope == "guild"
        assert event.content == "Guild message"
        assert event.message_id == "msg_003"
        assert event.user_name == "AliceNick"  # nick takes priority

    def test_parse_guild_at_message_create(self):
        """Test GUILD_AT_MESSAGE_CREATE parsing."""
        raw = make_guild_raw(content="@Bot help")
        
        event = EventParser.parse(EventType.GUILD_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.event_type == EventType.GUILD_AT_MESSAGE_CREATE
        assert event.chat_scope == "guild"
        # Note: guild messages do NOT strip @mention
        assert event.content == "@Bot help"

    def test_parse_guild_without_nick(self):
        """Test guild message falls back to username when nick is empty."""
        raw = make_guild_raw(nick="", username="Alice")
        
        event = EventParser.parse(EventType.GUILD_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.user_name == "Alice"

    def test_parse_guild_without_member(self):
        """Test guild message without member field."""
        raw = make_guild_raw()
        raw.pop("member")
        
        event = EventParser.parse(EventType.GUILD_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.user_name == "Alice"  # Falls back to author.username

    def test_parse_guild_missing_channel_id(self):
        """Test guild message without channel_id returns None."""
        raw = {
            "id": "msg_003",
            "content": "Guild message",
            "timestamp": "2026-04-27T10:02:00Z",
            "author": {"id": "USER_456", "username": "Alice"},
            # Missing channel_id
        }
        
        event = EventParser.parse(EventType.GUILD_MESSAGE_CREATE, raw)
        assert event is None

    def test_parse_guild_with_attachments(self):
        """Test guild message with attachments."""
        raw = make_guild_raw()
        raw["attachments"] = [
            {
                "url": "//example.com/voice.silk",
                "content_type": "audio/silk",
                "voice_wav_url": "https://example.com/voice.wav",
            }
        ]
        
        event = EventParser.parse(EventType.GUILD_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert len(event.attachments) == 1
        assert event.attachments[0].content_type == "audio/silk"


# ── Test Direct Message Parsing ───────────────────────────────────────

class TestParseDM:
    """Test DIRECT_MESSAGE_CREATE parsing."""

    def test_parse_dm_success(self):
        """Test successful DM parsing."""
        raw = make_dm_raw(
            guild_id="GUILD_789",
            user_id="USER_111",
            content="DM message",
            message_id="msg_004",
            timestamp="2026-04-27T10:03:00Z",
        )
        
        event = EventParser.parse(EventType.DIRECT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.event_type == EventType.DIRECT_MESSAGE_CREATE
        assert event.chat_id == "GUILD_789"
        assert event.user_id == "USER_111"
        assert event.chat_scope == "dm"
        assert event.content == "DM message"
        assert event.message_id == "msg_004"
        assert event.timestamp == "2026-04-27T10:03:00Z"

    def test_parse_dm_missing_guild_id(self):
        """Test DM without guild_id returns None."""
        raw = {
            "id": "msg_004",
            "content": "DM message",
            "timestamp": "2026-04-27T10:03:00Z",
            "author": {"id": "USER_111"},
            # Missing guild_id
        }
        
        event = EventParser.parse(EventType.DIRECT_MESSAGE_CREATE, raw)
        assert event is None

    def test_parse_dm_with_whitespace(self):
        """Test DM content whitespace stripping."""
        raw = make_dm_raw(content="  DM with spaces  ")
        
        event = EventParser.parse(EventType.DIRECT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "DM with spaces"


# ── Test Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_parse_empty_content(self):
        """Test parsing message with empty content."""
        raw = make_c2c_raw(content="")
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == ""

    def test_parse_whitespace_only_content(self):
        """Test parsing message with whitespace-only content."""
        raw = make_c2c_raw(content="   \n\t   ")
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == ""

    def test_parse_group_only_at_mention(self):
        """Test group message with only @mention."""
        raw = make_group_raw(content="@Bot")
        
        event = EventParser.parse(EventType.GROUP_AT_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == ""

    def test_parse_multiline_content(self):
        """Test parsing multiline content."""
        raw = make_c2c_raw(content="Line 1\nLine 2\nLine 3")
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "Line 1\nLine 2\nLine 3"

    def test_parse_unicode_content(self):
        """Test parsing Unicode content."""
        raw = make_c2c_raw(content="你好 🤖 Hello")
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.content == "你好 🤖 Hello"


# ── Test Integration ──────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for complete parsing flow."""

    def test_parse_all_supported_event_types(self):
        """Test parsing all supported event types."""
        test_cases = [
            (EventType.C2C_MESSAGE_CREATE, make_c2c_raw(), "c2c"),
            (EventType.GROUP_AT_MESSAGE_CREATE, make_group_raw(), "group"),
            (EventType.GUILD_MESSAGE_CREATE, make_guild_raw(), "guild"),
            (EventType.GUILD_AT_MESSAGE_CREATE, make_guild_raw(), "guild"),
            (EventType.DIRECT_MESSAGE_CREATE, make_dm_raw(), "dm"),
        ]
        
        for event_type, raw, expected_scope in test_cases:
            event = EventParser.parse(event_type, raw)
            assert event is not None, f"Failed to parse {event_type}"
            assert event.chat_scope == expected_scope
            assert event.event_type == event_type

    def test_event_handler_mapping(self):
        """Test _EVENT_HANDLERS mapping is complete."""
        # Ensure all MESSAGE_EVENT_TYPES are mapped
        from qqbot_agent_sdk.dto import MESSAGE_EVENT_TYPES
        
        for event_type in MESSAGE_EVENT_TYPES:
            assert event_type in EventParser._EVENT_HANDLERS, \
                f"{event_type} not in _EVENT_HANDLERS"

    def test_parse_preserves_raw_data(self):
        """Test that raw data is preserved in InboundEvent."""
        raw = make_c2c_raw()
        raw["extra_field"] = "extra_value"
        
        event = EventParser.parse(EventType.C2C_MESSAGE_CREATE, raw)
        
        assert event is not None
        assert event.raw is not None
        assert event.raw["extra_field"] == "extra_value"
