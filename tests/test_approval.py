# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.approval module.

Tests cover:
- parse_approval_button_data() - parsing approval button payloads
- parse_update_prompt_button_data() - parsing update-prompt payloads
- build_approval_keyboard() - keyboard structure and button_data format
- build_update_prompt_keyboard() - Yes/No keyboard structure
- build_approval_text() - markdown text generation (exec & plugin)
- ApprovalSender.send() - message sending with keyboard
"""

from unittest.mock import AsyncMock, patch

import pytest

from qqbot_agent_sdk.approval import (
    ApprovalRequest,
    ApprovalSender,
    build_approval_keyboard,
    build_approval_text,
    build_update_prompt_keyboard,
    parse_approval_button_data,
    parse_update_prompt_button_data,
)
from qqbot_agent_sdk.api_client import QQApiClient
from qqbot_agent_sdk.dto import MessageToCreate


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    """Mock QQApiClient."""
    return QQApiClient(app_id="test_app", client_secret="test_secret")


@pytest.fixture
def approval_sender(api_client):
    """ApprovalSender with mocked API client."""
    return ApprovalSender(api_client, log_tag="TestBot")


# ── Test parse_approval_button_data ───────────────────────────────────

class TestParseApprovalButtonData:
    """Test parse_approval_button_data() function."""

    def test_parse_allow_once(self):
        """Test parsing 'allow-once' decision."""
        result = parse_approval_button_data("approve:session123:allow-once")
        assert result == ("session123", "allow-once")

    def test_parse_allow_session_rejected(self):
        """Test 'allow-session' is rejected after removal from regex."""
        result = parse_approval_button_data("approve:mykey:allow-session")
        assert result is None

    def test_parse_allow_always(self):
        """Test parsing 'allow-always' decision."""
        result = parse_approval_button_data("approve:key:allow-always")
        assert result == ("key", "allow-always")

    def test_parse_deny(self):
        """Test parsing 'deny' decision."""
        result = parse_approval_button_data("approve:xyz:deny")
        assert result == ("xyz", "deny")

    def test_parse_session_key_with_colons(self):
        """Test parsing session_key containing colons."""
        result = parse_approval_button_data(
            "approve:agent:main:qqbot:c2c:OPENID123:allow-once"
        )
        assert result == ("agent:main:qqbot:c2c:OPENID123", "allow-once")

    def test_parse_invalid_prefix(self):
        """Test parsing with wrong prefix returns None."""
        result = parse_approval_button_data("deny:session123:allow-once")
        assert result is None

    def test_parse_invalid_decision(self):
        """Test parsing with invalid decision returns None."""
        result = parse_approval_button_data("approve:session123:maybe")
        assert result is None

    def test_parse_missing_colon(self):
        """Test parsing with missing colon returns None."""
        result = parse_approval_button_data("approve:session123")
        assert result is None

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = parse_approval_button_data("")
        assert result is None


# ── Test parse_update_prompt_button_data ──────────────────────────────

class TestParseUpdatePromptButtonData:
    """Test parse_update_prompt_button_data() function."""

    def test_parse_yes(self):
        """Test parsing 'y' answer."""
        result = parse_update_prompt_button_data("update_prompt:y")
        assert result == "y"

    def test_parse_no(self):
        """Test parsing 'n' answer."""
        result = parse_update_prompt_button_data("update_prompt:n")
        assert result == "n"

    def test_parse_invalid_prefix(self):
        """Test parsing with wrong prefix returns None."""
        result = parse_update_prompt_button_data("approve:y")
        assert result is None

    def test_parse_invalid_answer(self):
        """Test parsing with invalid answer returns None."""
        result = parse_update_prompt_button_data("update_prompt:maybe")
        assert result is None

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = parse_update_prompt_button_data("")
        assert result is None


# ── Test build_approval_keyboard ──────────────────────────────────────

class TestBuildApprovalKeyboard:
    """Test build_approval_keyboard() function."""

    def test_keyboard_structure(self):
        """Test keyboard has correct structure."""
        keyboard = build_approval_keyboard("test_session")
        
        assert keyboard.content is not None
        assert len(keyboard.content.rows) == 1
        assert len(keyboard.content.rows[0].buttons) == 3

    def test_button_ids(self):
        """Test button IDs are correct."""
        keyboard = build_approval_keyboard("test_session")
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].id == "allow"
        assert buttons[1].id == "always"
        assert buttons[2].id == "deny"

    def test_button_labels(self):
        """Test button labels."""
        keyboard = build_approval_keyboard("test_session")
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].render_data.label == "✅ 允许一次"
        assert buttons[1].render_data.label == "⭐ 始终允许"
        assert buttons[2].render_data.label == "❌ 拒绝"

    def test_button_data_format(self):
        """Test button_data format matches pattern."""
        session_key = "agent:main:c2c:USER123"
        keyboard = build_approval_keyboard(session_key)
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].action.data == f"approve:{session_key}:allow-once"
        assert buttons[1].action.data == f"approve:{session_key}:allow-always"
        assert buttons[2].action.data == f"approve:{session_key}:deny"

    def test_button_group_id(self):
        """Test all buttons share same group_id."""
        keyboard = build_approval_keyboard("test_session")
        buttons = keyboard.content.rows[0].buttons
        
        for button in buttons:
            assert button.group_id == "approval"

    def test_button_click_limit(self):
        """Test buttons have click_limit=1."""
        keyboard = build_approval_keyboard("test_session")
        buttons = keyboard.content.rows[0].buttons
        
        for button in buttons:
            assert button.action.click_limit == 1

    def test_button_styles(self):
        """Test button styles (allow=1, deny=0)."""
        keyboard = build_approval_keyboard("test_session")
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].render_data.style == 1  # allow-once
        assert buttons[1].render_data.style == 1  # allow-always
        assert buttons[2].render_data.style == 0  # deny


# ── Test build_update_prompt_keyboard ─────────────────────────────────

class TestBuildUpdatePromptKeyboard:
    """Test build_update_prompt_keyboard() function."""

    def test_keyboard_structure(self):
        """Test keyboard has correct structure."""
        keyboard = build_update_prompt_keyboard()
        
        assert keyboard.content is not None
        assert len(keyboard.content.rows) == 1
        assert len(keyboard.content.rows[0].buttons) == 2

    def test_button_ids(self):
        """Test button IDs are correct."""
        keyboard = build_update_prompt_keyboard()
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].id == "yes"
        assert buttons[1].id == "no"

    def test_button_labels(self):
        """Test button labels."""
        keyboard = build_update_prompt_keyboard()
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].render_data.label == "✓ 确认"
        assert buttons[1].render_data.label == "✗ 取消"

    def test_button_data_format(self):
        """Test button_data format."""
        keyboard = build_update_prompt_keyboard()
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].action.data == "update_prompt:y"
        assert buttons[1].action.data == "update_prompt:n"

    def test_button_group_id(self):
        """Test all buttons share same group_id."""
        keyboard = build_update_prompt_keyboard()
        buttons = keyboard.content.rows[0].buttons
        
        for button in buttons:
            assert button.group_id == "update_prompt"

    def test_button_styles(self):
        """Test button styles (yes=1, no=0)."""
        keyboard = build_update_prompt_keyboard()
        buttons = keyboard.content.rows[0].buttons
        
        assert buttons[0].render_data.style == 1  # yes
        assert buttons[1].render_data.style == 0  # no


# ── Test build_approval_text ──────────────────────────────────────────

class TestBuildApprovalText:
    """Test build_approval_text() function."""

    def test_exec_approval_with_command(self):
        """Test exec approval text with command preview."""
        req = ApprovalRequest(
            session_key="test",
            title="Run command",
            command_preview="rm -rf /tmp/data",
            cwd="/home/user",
            timeout_sec=60,
        )
        text = build_approval_text(req)
        
        assert "🔐 **命令执行审批**" in text
        assert "rm -rf /tmp/data" in text
        assert "📁 目录: /home/user" in text
        assert "⏱️ 超时: 60 秒" in text

    def test_exec_approval_with_long_command(self):
        """Test exec approval truncates long commands."""
        req = ApprovalRequest(
            session_key="test",
            title="Long command",
            command_preview="b" * 400,
            timeout_sec=120,
        )
        text = build_approval_text(req)
        
        # Should truncate command_preview to 300 chars
        # title "Long command" is also included, so check command chars only
        assert text.count("b") == 300
        assert "📋 Long command" in text

    def test_exec_approval_with_description(self):
        """Test exec approval includes description."""
        req = ApprovalRequest(
            session_key="test",
            title="Deploy",
            command_preview="./deploy.sh",
            description="Deploy to production",
            timeout_sec=180,
        )
        text = build_approval_text(req)
        
        assert "📝 Deploy to production" in text

    def test_plugin_approval_default(self):
        """Test plugin approval text (no command/cwd)."""
        req = ApprovalRequest(
            session_key="test",
            title="Access file system",
            tool_name="file_manager",
            timeout_sec=90,
        )
        text = build_approval_text(req)
        
        assert "🟡 **审批请求**" in text
        assert "📋 Access file system" in text
        assert "🔧 工具: file_manager" in text
        assert "⏱️ 超时: 90 秒" in text

    def test_plugin_approval_critical_severity(self):
        """Test plugin approval with critical severity."""
        req = ApprovalRequest(
            session_key="test",
            title="Delete data",
            severity="critical",
            timeout_sec=60,
        )
        text = build_approval_text(req)
        
        assert "🔴 **审批请求**" in text

    def test_plugin_approval_info_severity(self):
        """Test plugin approval with info severity."""
        req = ApprovalRequest(
            session_key="test",
            title="Read logs",
            severity="info",
            timeout_sec=30,
        )
        text = build_approval_text(req)
        
        assert "🔵 **审批请求**" in text

    def test_plugin_approval_with_description(self):
        """Test plugin approval includes description."""
        req = ApprovalRequest(
            session_key="test",
            title="Send email",
            description="Send notification to admin",
            tool_name="email_sender",
            timeout_sec=45,
        )
        text = build_approval_text(req)
        
        assert "📝 Send notification to admin" in text


# ── Test ApprovalSender ───────────────────────────────────────────────

class TestApprovalSender:
    """Test ApprovalSender class."""

    @pytest.mark.asyncio
    async def test_send_c2c_success(self, approval_sender):
        """Test sending approval to C2C chat."""
        req = ApprovalRequest(
            session_key="test_session",
            title="Test approval",
            timeout_sec=60,
        )
        
        with patch.object(
            approval_sender._api,
            "build_text_body",
            return_value=MessageToCreate(content="test", msg_type=0, msg_seq=1, msg_id=""),
        ) as mock_build, \
        patch.object(
            approval_sender._api,
            "post_c2c_message",
            new_callable=AsyncMock,
            return_value={"id": "msg123"},
        ) as mock_post:
            result = await approval_sender.send("c2c", "user_openid", req, msg_id="reply123")
        
        assert result is True
        mock_build.assert_called_once()
        mock_post.assert_called_once()
        
        # Verify keyboard was passed
        call_kwargs = mock_post.call_args.kwargs
        assert "keyboard" in call_kwargs
        keyboard = call_kwargs["keyboard"]
        assert keyboard.content.rows[0].buttons[0].action.data.startswith("approve:test_session:")

    @pytest.mark.asyncio
    async def test_send_group_success(self, approval_sender):
        """Test sending approval to group chat."""
        req = ApprovalRequest(
            session_key="group_session",
            title="Group approval",
            command_preview="ls -la",
            cwd="/tmp",
            timeout_sec=120,
        )
        
        with patch.object(
            approval_sender._api,
            "build_text_body",
            return_value=MessageToCreate(content="test", msg_type=0, msg_seq=1, msg_id=""),
        ), \
        patch.object(
            approval_sender._api,
            "post_group_message",
            new_callable=AsyncMock,
            return_value={"id": "msg456"},
        ) as mock_post:
            result = await approval_sender.send("group", "group_openid", req)
        
        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_unsupported_chat_type(self, approval_sender):
        """Test sending with unsupported chat_type returns False."""
        req = ApprovalRequest(
            session_key="test",
            title="Test",
            timeout_sec=60,
        )
        
        with patch.object(
            approval_sender._api,
            "build_text_body",
            return_value=MessageToCreate(content="test", msg_type=0, msg_seq=1, msg_id=""),
        ):
            result = await approval_sender.send("guild", "channel_id", req)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_exception_returns_false(self, approval_sender):
        """Test send() returns False when API call raises exception."""
        req = ApprovalRequest(
            session_key="test",
            title="Test",
            timeout_sec=60,
        )
        
        with patch.object(
            approval_sender._api,
            "build_text_body",
            return_value=MessageToCreate(content="test", msg_type=0, msg_seq=1, msg_id=""),
        ), \
        patch.object(
            approval_sender._api,
            "post_c2c_message",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Network error"),
        ):
            result = await approval_sender.send("c2c", "user_id", req)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_without_msg_id(self, approval_sender):
        """Test sending without msg_id (active message)."""
        req = ApprovalRequest(
            session_key="active_session",
            title="Active approval",
            timeout_sec=90,
        )
        
        with patch.object(
            approval_sender._api,
            "build_text_body",
            return_value=MessageToCreate(content="test", msg_type=0, msg_seq=1, msg_id=""),
        ) as mock_build, \
        patch.object(
            approval_sender._api,
            "post_c2c_message",
            new_callable=AsyncMock,
            return_value={"id": "msg789"},
        ):
            result = await approval_sender.send("c2c", "user_id", req, msg_id=None)
        
        assert result is True
        # build_text_body should be called with reply_to=None
        call_args = mock_build.call_args
        assert call_args.kwargs.get("reply_to") is None


# ── Test Integration ──────────────────────────────────────────────────

class TestApprovalIntegration:
    """Integration tests for approval flow."""

    def test_approval_roundtrip(self):
        """Test building keyboard and parsing button_data."""
        session_key = "agent:main:qqbot:c2c:USER_OPENID"
        
        # Build keyboard
        keyboard = build_approval_keyboard(session_key)
        allow_button = keyboard.content.rows[0].buttons[0]
        
        # Parse button_data
        parsed = parse_approval_button_data(allow_button.action.data)
        
        assert parsed is not None
        assert parsed[0] == session_key
        assert parsed[1] == "allow-once"

    def test_update_prompt_roundtrip(self):
        """Test building update-prompt keyboard and parsing button_data."""
        keyboard = build_update_prompt_keyboard()
        yes_button = keyboard.content.rows[0].buttons[0]
        
        # Parse button_data
        parsed = parse_update_prompt_button_data(yes_button.action.data)
        
        assert parsed == "y"

    def test_exec_vs_plugin_text_detection(self):
        """Test build_approval_text() chooses correct format."""
        # Exec approval (has command_preview)
        exec_req = ApprovalRequest(
            session_key="test",
            title="Command",
            command_preview="echo hello",
            timeout_sec=60,
        )
        exec_text = build_approval_text(exec_req)
        assert "🔐 **命令执行审批**" in exec_text
        
        # Plugin approval (no command_preview or cwd)
        plugin_req = ApprovalRequest(
            session_key="test",
            title="Plugin action",
            tool_name="plugin",
            timeout_sec=60,
        )
        plugin_text = build_approval_text(plugin_req)
        assert "**审批请求**" in plugin_text
