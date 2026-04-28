# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.api_client module.

Tests cover:
- QQApiClient token lifecycle (ensure_token_sync, ensure_token)
- HTTP request methods (request, get_gateway_url, etc.)
- Message sending (C2C, group, guild)
- Media upload endpoints
- Chunked upload flow
- Helper methods (next_msg_seq, build_text_body)
- Error handling and retries
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qqbot_agent_sdk.api_client import QQApiClient, Route
from qqbot_agent_sdk.dto import (
    FileHashInfo,
    InlineKeyboard,
    KeyboardButton,
    KeyboardButtonAction,
    KeyboardButtonRenderData,
    KeyboardContent,
    KeyboardRow,
    MessageToCreate,
    QQMessageType,
    RichMediaMessage,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Create a QQApiClient instance for testing."""
    return QQApiClient(
        app_id="test_app_id",
        client_secret="test_secret",
        log_tag="TestBot",
    )


@pytest.fixture
def mock_http_client():
    """Create a mock async HTTP client."""
    mock = AsyncMock()
    mock.request = AsyncMock()
    mock.get = AsyncMock()
    mock.post = AsyncMock()
    return mock


# ── Token Management Tests ────────────────────────────────────────────────


class TestTokenManagement:
    """Test token lifecycle: ensure_token_sync, ensure_token, clear_token."""

    def test_init_state(self, client):
        """Test initial state after construction."""
        assert client._app_id == "test_app_id"
        assert client._client_secret == "test_secret"
        assert client._log_tag == "TestBot"
        assert client._access_token is None
        assert client._token_expires_at == 0.0
        assert client._http_client is None

    def test_access_token_property(self, client):
        """Test access_token property getter."""
        assert client.access_token is None
        client._access_token = "test_token"
        assert client.access_token == "test_token"

    def test_setup_http_client(self, client, mock_http_client):
        """Test setup() injects HTTP client."""
        client.setup(mock_http_client)
        assert client._http_client is mock_http_client

    @patch("httpx.post")
    def test_ensure_token_sync_success(self, mock_post, client):
        """Test ensure_token_sync() fetches new token successfully."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new_token_123",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        token = client.ensure_token_sync()

        assert token == "new_token_123"
        assert client._access_token == "new_token_123"
        assert client._token_expires_at > time.time()

        # Verify request headers
        call_kwargs = mock_post.call_args[1]
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["Content-Type"] == "application/json"
        assert "User-Agent" in call_kwargs["headers"]

    @patch("httpx.post")
    def test_ensure_token_sync_uses_cached_token(self, mock_post, client):
        """Test ensure_token_sync() returns cached token if valid."""
        client._access_token = "cached_token"
        client._token_expires_at = time.time() + 3600

        token = client.ensure_token_sync()

        assert token == "cached_token"
        mock_post.assert_not_called()

    @patch("httpx.post")
    def test_ensure_token_sync_refreshes_expired_token(self, mock_post, client):
        """Test ensure_token_sync() refreshes expired token."""
        client._access_token = "old_token"
        client._token_expires_at = time.time() - 100  # Expired

        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        token = client.ensure_token_sync()

        assert token == "new_token"
        mock_post.assert_called_once()

    @patch("httpx.post")
    def test_ensure_token_sync_handles_missing_token(self, mock_post, client):
        """Test ensure_token_sync() raises when token missing in response."""
        mock_response = Mock()
        mock_response.json.return_value = {"expires_in": 7200}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="missing access_token"):
            client.ensure_token_sync()

    @patch("httpx.post")
    def test_ensure_token_sync_handles_http_error(self, mock_post, client):
        """Test ensure_token_sync() handles HTTP errors."""
        mock_post.side_effect = Exception("Network error")

        with pytest.raises(RuntimeError, match="Failed to get QQ Bot access token"):
            client.ensure_token_sync()

    @patch("httpx.post")
    def test_ensure_token_sync_thread_safety(self, mock_post, client):
        """Test ensure_token_sync() is thread-safe (uses lock)."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "thread_safe_token",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Simulate concurrent calls
        results = []

        def call_token():
            results.append(client.ensure_token_sync())

        import threading

        threads = [threading.Thread(target=call_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should only call API once due to lock
        assert mock_post.call_count == 1
        assert all(r == "thread_safe_token" for r in results)

    async def test_ensure_token_async(self, client):
        """Test ensure_token() async wrapper."""
        with patch.object(client, "ensure_token_sync", return_value="async_token"):
            token = await client.ensure_token()
            assert token == "async_token"

    def test_clear_token(self, client):
        """Test clear_token() invalidates cached token."""
        client._access_token = "old_token"
        client._token_expires_at = time.time() + 3600

        client.clear_token()

        assert client._access_token is None
        assert client._token_expires_at == 0.0


# ── Gateway Tests ─────────────────────────────────────────────────────────


class TestGateway:
    """Test WebSocket gateway URL retrieval."""

    @patch("httpx.get")
    @patch("httpx.post")
    def test_get_gateway_url_sync_success(self, mock_post, mock_get, client):
        """Test get_gateway_url_sync() fetches gateway URL."""
        # Mock token response
        token_response = Mock()
        token_response.json.return_value = {
            "access_token": "token_123",
            "expires_in": 7200,
        }
        token_response.raise_for_status = Mock()

        # Mock gateway response
        gateway_response = Mock()
        gateway_response.json.return_value = {"url": "wss://gateway.qq.com"}
        gateway_response.raise_for_status = Mock()
        gateway_response.status_code = 200
        gateway_response.headers = {"x-tps-trace-id": "trace-123"}

        mock_post.return_value = token_response
        mock_get.return_value = gateway_response

        url = client.get_gateway_url_sync()

        assert url == "wss://gateway.qq.com"
        mock_get.assert_called_once()

    @patch("httpx.get")
    @patch("httpx.post")
    def test_get_gateway_url_sync_missing_url(self, mock_post, mock_get, client):
        """Test get_gateway_url_sync() raises when URL missing."""
        token_response = Mock()
        token_response.json.return_value = {
            "access_token": "token_123",
            "expires_in": 7200,
        }
        token_response.raise_for_status = Mock()

        gateway_response = Mock()
        gateway_response.json.return_value = {}
        gateway_response.raise_for_status = Mock()
        gateway_response.status_code = 200
        gateway_response.headers = {}

        mock_post.return_value = token_response
        mock_get.return_value = gateway_response

        with pytest.raises(RuntimeError, match="missing url"):
            client.get_gateway_url_sync()

    async def test_get_gateway_url_async(self, client, mock_http_client):
        """Test get_gateway_url() async method."""
        client.setup(mock_http_client)

        mock_response = Mock()
        mock_response.json.return_value = {"url": "wss://gateway.qq.com"}
        mock_response.content = b'{"url":"wss://gateway.qq.com"}'
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_http_client.request.return_value = mock_response

        with patch.object(client, "ensure_token", return_value="test_token"):
            url = await client.get_gateway_url()

        assert url == "wss://gateway.qq.com"


# ── Generic Request Tests ─────────────────────────────────────────────────


class TestGenericRequest:
    """Test generic authenticated request() method."""

    async def test_request_success(self, client, mock_http_client):
        """Test request() makes authenticated API call."""
        client.setup(mock_http_client)

        mock_response = Mock()
        mock_response.json.return_value = {"message_id": "msg_123"}
        mock_response.content = b'{"message_id":"msg_123"}'
        mock_response.status_code = 200
        mock_response.headers = {"x-tps-trace-id": "trace-456"}
        mock_http_client.request.return_value = mock_response

        with patch.object(client, "ensure_token", return_value="test_token"):
            result = await client.request("POST", "/v2/users/user_123/messages")

        assert result == {"message_id": "msg_123"}
        mock_http_client.request.assert_called_once()

        # Verify headers
        call_kwargs = mock_http_client.request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "QQBot test_token"
        assert call_kwargs["headers"]["Content-Type"] == "application/json"

    async def test_request_without_http_client(self, client):
        """Test request() raises when HTTP client not initialized."""
        with pytest.raises(RuntimeError, match="HTTP client not initialized"):
            await client.request("GET", "/test")

    async def test_request_handles_http_error(self, client, mock_http_client):
        """Test request() handles HTTP error responses."""
        client.setup(mock_http_client)

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.headers = {"x-tps-trace-id": "trace-error"}
        mock_response.json.return_value = {"message": "Not found"}
        mock_http_client.request.return_value = mock_response

        with patch.object(client, "ensure_token", return_value="test_token"):
            with pytest.raises(RuntimeError, match="QQ Bot API error"):
                await client.request("GET", "/v2/invalid")

    async def test_request_handles_timeout(self, client, mock_http_client):
        """Test request() handles timeout exceptions."""
        client.setup(mock_http_client)

        import httpx

        mock_http_client.request.side_effect = httpx.TimeoutException("Timeout")

        with patch.object(client, "ensure_token", return_value="test_token"):
            with pytest.raises(RuntimeError, match="timeout"):
                await client.request("GET", "/v2/test")

    async def test_request_empty_response(self, client, mock_http_client):
        """Test request() handles empty response body."""
        client.setup(mock_http_client)

        mock_response = Mock()
        mock_response.content = b""
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_http_client.request.return_value = mock_response

        with patch.object(client, "ensure_token", return_value="test_token"):
            result = await client.request("DELETE", "/v2/test")

        assert result == {}


# ── Message Sending Tests ─────────────────────────────────────────────────


class TestMessageSending:
    """Test message sending methods (C2C, group, guild)."""

    async def test_post_c2c_message(self, client, mock_http_client):
        """Test post_c2c_message() sends message to user."""
        client.setup(mock_http_client)

        msg = MessageToCreate(
            content="Hello",
            msg_type=QQMessageType.TEXT,
            msg_seq=123,
        )

        with patch.object(
            client, "request", return_value={"id": "msg_c2c"}
        ) as mock_request:
            result = await client.post_c2c_message("user_123", msg)

        assert result == {"id": "msg_c2c"}
        mock_request.assert_called_once()
        # Check Route object was used
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/users/user_123/messages"
        assert route.method == "POST"

    async def test_post_c2c_message_with_keyboard(self, client, mock_http_client):
        """Test post_c2c_message() with inline keyboard."""
        client.setup(mock_http_client)

        msg = MessageToCreate(
            content="Choose",
            msg_type=QQMessageType.TEXT,
            msg_seq=123,
        )
        keyboard = InlineKeyboard(
            content=KeyboardContent(
                rows=[
                    KeyboardRow(
                        buttons=[
                            KeyboardButton(
                                id="btn_1",
                                render_data=KeyboardButtonRenderData(
                                    label="Yes", visited_label="Clicked"
                                ),
                                action=KeyboardButtonAction(type=1, data="yes"),
                            )
                        ]
                    )
                ]
            )
        )

        with patch.object(
            client, "request", return_value={"id": "msg_kb"}
        ) as mock_request:
            result = await client.post_c2c_message("user_123", msg, keyboard=keyboard)

        assert result == {"id": "msg_kb"}
        # Verify body contains keyboard
        call_args = mock_request.call_args[0]
        body = call_args[1]  # Second argument to request() is body
        assert "keyboard" in body

    async def test_post_group_message(self, client, mock_http_client):
        """Test post_group_message() sends message to group."""
        client.setup(mock_http_client)

        msg = MessageToCreate(
            content="Group message",
            msg_type=QQMessageType.TEXT,
            msg_seq=456,
        )

        with patch.object(
            client, "request", return_value={"id": "msg_group"}
        ) as mock_request:
            result = await client.post_group_message("group_789", msg)

        assert result == {"id": "msg_group"}
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/groups/group_789/messages"

    async def test_post_guild_message(self, client, mock_http_client):
        """Test post_guild_message() sends message to guild channel."""
        client.setup(mock_http_client)

        from qqbot_agent_sdk.dto import GuildMessageToCreate

        msg = GuildMessageToCreate(content="Guild message")

        with patch.object(
            client, "request", return_value={"id": "msg_guild"}
        ) as mock_request:
            result = await client.post_guild_message("channel_111", msg)

        assert result == {"id": "msg_guild"}
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/channels/channel_111/messages"


# ── Media Upload Tests ────────────────────────────────────────────────────


class TestMediaUpload:
    """Test media upload endpoints (simple and chunked)."""

    async def test_upload_c2c_file(self, client, mock_http_client):
        """Test upload_c2c_file() uploads media to user."""
        client.setup(mock_http_client)

        msg = RichMediaMessage(file_type=1, url="http://example.com/image.jpg")

        with patch.object(
            client, "request", return_value={"file_uuid": "uuid_c2c"}
        ) as mock_request:
            result = await client.upload_c2c_file("user_123", msg)

        assert result == {"file_uuid": "uuid_c2c"}
        call_args = mock_request.call_args
        route = call_args[0][0]
        from qqbot_agent_sdk.api_client import Route
        assert isinstance(route, Route)
        assert route.full_path == "/v2/users/user_123/files"

    async def test_upload_group_file(self, client, mock_http_client):
        """Test upload_group_file() uploads media to group."""
        client.setup(mock_http_client)

        msg = RichMediaMessage(file_type=4, file_data="base64data")

        with patch.object(
            client, "request", return_value={"file_uuid": "uuid_group"}
        ) as mock_request:
            result = await client.upload_group_file("group_456", msg)

        assert result == {"file_uuid": "uuid_group"}
        call_args = mock_request.call_args
        route = call_args[0][0]
        from qqbot_agent_sdk.api_client import Route
        assert isinstance(route, Route)
        assert route.full_path == "/v2/groups/group_456/files"

    async def test_upload_c2c_prepare(self, client, mock_http_client):
        """Test upload_c2c_prepare() for chunked upload."""
        client.setup(mock_http_client)

        hashes = FileHashInfo(
            md5="md5_hash", sha1="sha1_hash", md5_10m="md5_10m_hash"
        )

        with patch.object(
            client,
            "request",
            return_value={
                "upload_id": "upload_123",
                "block_size": 1048576,
                "parts": [{"part_index": 1, "upload_url": "http://cos.com/part1"}],
            },
        ) as mock_request:
            result = await client.upload_c2c_prepare(
                "user_123", 1, "image.jpg", 2000000, hashes
            )

        assert result.upload_id == "upload_123"
        assert result.block_size == 1048576
        
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/users/user_123/upload_prepare"

    async def test_upload_group_prepare(self, client, mock_http_client):
        """Test upload_group_prepare() for chunked upload."""
        client.setup(mock_http_client)

        hashes = FileHashInfo(
            md5="md5_hash", sha1="sha1_hash", md5_10m="md5_10m_hash"
        )

        with patch.object(
            client,
            "request",
            return_value={
                "upload_id": "upload_456",
                "block_size": 1048576,
                "parts": [{"part_index": 1, "upload_url": "http://cos.com/part1"}],
            },
        ) as mock_request:
            result = await client.upload_group_prepare(
                "group_456", 1, "video.mp4", 5000000, hashes
            )

        assert result.upload_id == "upload_456"
        
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/groups/group_456/upload_prepare"

    async def test_upload_c2c_part_finish(self, client, mock_http_client):
        """Test upload_c2c_part_finish() notifies part completion."""
        client.setup(mock_http_client)

        with patch.object(client, "request", return_value={}) as mock_request:
            await client.upload_c2c_part_finish(
                "user_123", "upload_123", 1, 1048576, "part_md5"
            )

        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/users/user_123/upload_part_finish"

    async def test_upload_group_part_finish(self, client, mock_http_client):
        """Test upload_group_part_finish() notifies part completion."""
        client.setup(mock_http_client)

        with patch.object(client, "request", return_value={}) as mock_request:
            await client.upload_group_part_finish(
                "group_456", "upload_123", 1, 1048576, "part_md5"
            )

        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/groups/group_456/upload_part_finish"

    async def test_complete_c2c_upload(self, client, mock_http_client):
        """Test complete_c2c_upload() finishes chunked upload."""
        client.setup(mock_http_client)

        with patch.object(
            client,
            "request",
            return_value={
                "file_info": "file_info_data",
                "file_uuid": "final_uuid",
                "ttl": 86400,
            },
        ) as mock_request:
            result = await client.complete_c2c_upload("user_123", "upload_123")

        assert result.file_uuid == "final_uuid"
        assert result.ttl == 86400
        
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/users/user_123/files"

    async def test_complete_group_upload(self, client, mock_http_client):
        """Test complete_group_upload() finishes chunked upload."""
        client.setup(mock_http_client)

        with patch.object(
            client,
            "request",
            return_value={
                "file_info": "file_info_data",
                "file_uuid": "final_uuid2",
                "ttl": 86400,
            },
        ) as mock_request:
            result = await client.complete_group_upload("group_456", "upload_456")

        assert result.file_uuid == "final_uuid2"
        
        call_args = mock_request.call_args
        route = call_args[0][0]
        assert isinstance(route, Route)
        assert route.full_path == "/v2/groups/group_456/files"
        mock_request.assert_called_once()


# ── Interaction Tests ─────────────────────────────────────────────────────


class TestInteraction:
    """Test interaction (button callback) acknowledgment."""

    async def test_acknowledge_interaction(self, client, mock_http_client):
        """Test acknowledge_interaction() ACKs button click."""
        client.setup(mock_http_client)

        with patch.object(client, "request", return_value={}) as mock_request:
            await client.acknowledge_interaction("interaction_123", code=0)

        call_args = mock_request.call_args[0]
        # Check Route object was used
        route = call_args[0]
        from qqbot_agent_sdk.api_client import Route
        assert isinstance(route, Route)
        assert route.full_path == "/interactions/interaction_123"
        assert route.method == "PUT"
        assert call_args[1] == {"code": 0}

    async def test_acknowledge_interaction_with_data(self, client, mock_http_client):
        """Test acknowledge_interaction() with custom data."""
        client.setup(mock_http_client)

        with patch.object(client, "request", return_value={}) as mock_request:
            await client.acknowledge_interaction(
                "interaction_456", code=0, data={"claw_cfg": {"key": "value"}}
            )

        call_args = mock_request.call_args[0]
        body = call_args[1]
        assert body["data"] == {"claw_cfg": {"key": "value"}}


# ── Helper Methods Tests ──────────────────────────────────────────────────


class TestHelperMethods:
    """Test helper methods: next_msg_seq, build_text_body."""

    def test_next_msg_seq_range(self, client):
        """Test next_msg_seq() returns value in valid range."""
        for _ in range(100):
            seq = QQApiClient.next_msg_seq()
            assert 0 <= seq <= 65535

    def test_next_msg_seq_uniqueness(self, client):
        """Test next_msg_seq() generates different values."""
        seqs = {QQApiClient.next_msg_seq() for _ in range(50)}
        assert len(seqs) > 40  # Should be mostly unique

    def test_build_text_body_plain_text(self, client):
        """Test build_text_body() creates plain text message."""
        msg = QQApiClient.build_text_body("Hello", markdown=False)

        assert msg.content == "Hello"
        assert msg.msg_type == QQMessageType.TEXT
        assert 0 <= msg.msg_seq <= 65535

    def test_build_text_body_markdown(self, client):
        """Test build_text_body() creates markdown message."""
        msg = QQApiClient.build_text_body("**Bold**", markdown=True)

        assert msg.msg_type == QQMessageType.MARKDOWN
        assert msg.markdown is not None
        assert msg.markdown.content == "**Bold**"

    def test_build_text_body_with_reply(self, client):
        """Test build_text_body() with reply_to parameter."""
        msg = QQApiClient.build_text_body(
            "Reply", reply_to="msg_original", markdown=False
        )

        assert msg.msg_id == "msg_original"
        assert msg.message_reference is not None
        assert msg.message_reference.message_id == "msg_original"

    def test_build_text_body_truncation(self, client):
        """Test build_text_body() truncates long content."""
        long_text = "x" * 10000
        msg = QQApiClient.build_text_body(long_text, max_length=100)

        assert len(msg.markdown.content) == 100

    def test_build_text_body_markdown_reply(self, client):
        """Test build_text_body() markdown with reply."""
        msg = QQApiClient.build_text_body("Reply", reply_to="msg_123", markdown=True)

        assert msg.msg_id == "msg_123"
        assert msg.msg_type == QQMessageType.MARKDOWN


# ── High-level Send Methods Tests ─────────────────────────────────────────


class TestSendHelpers:
    """Test high-level send_text() and send_typing() methods."""

    async def test_send_text_c2c(self, client, mock_http_client):
        """Test send_text() sends C2C message."""
        client.setup(mock_http_client)

        with patch.object(
            client, "post_c2c_message", return_value={"id": "sent_c2c"}
        ) as mock_post:
            result = await client.send_text("c2c", "user_123", "Hello")

        assert result == {"id": "sent_c2c"}
        mock_post.assert_called_once()

    async def test_send_text_group(self, client, mock_http_client):
        """Test send_text() sends group message."""
        client.setup(mock_http_client)

        with patch.object(
            client, "post_group_message", return_value={"id": "sent_group"}
        ) as mock_post:
            result = await client.send_text("group", "group_456", "Hi group")

        assert result == {"id": "sent_group"}
        mock_post.assert_called_once()

    async def test_send_text_guild(self, client, mock_http_client):
        """Test send_text() sends guild message."""
        client.setup(mock_http_client)

        with patch.object(
            client, "post_guild_message", return_value={"id": "sent_guild"}
        ) as mock_post:
            result = await client.send_text("guild", "channel_789", "Guild message")

        assert result == {"id": "sent_guild"}
        mock_post.assert_called_once()

    async def test_send_text_with_retry(self, client, mock_http_client):
        """Test send_text() retries on transient errors.

        retries=3 means total 3 attempts (1 initial + 2 retries).
        """
        client.setup(mock_http_client)

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("Transient error")
            return {"id": "sent_after_retry"}

        with patch.object(client, "post_c2c_message", side_effect=mock_post):
            result = await client.send_text("c2c", "user_123", "Retry test", retries=3)

        assert result == {"id": "sent_after_retry"}
        assert call_count == 2

    async def test_send_text_retries_zero_runs_once(self, client, mock_http_client):
        """Test send_text() with retries=0 still runs at least once."""
        client.setup(mock_http_client)

        with patch.object(
            client,
            "post_c2c_message",
            side_effect=RuntimeError("Transient error"),
        ):
            with pytest.raises(RuntimeError, match="send_text failed after 1 attempts"):
                await client.send_text("c2c", "user_123", "Test", retries=0)

    async def test_send_text_fatal_error_no_retry(self, client, mock_http_client):
        """Test send_text() doesn't retry fatal errors."""
        client.setup(mock_http_client)

        with patch.object(
            client,
            "post_c2c_message",
            side_effect=RuntimeError("403 Forbidden: permission denied"),
        ):
            with pytest.raises(RuntimeError, match="(Forbidden|permission)"):
                await client.send_text("c2c", "user_123", "Fatal error test", retries=3)

    async def test_send_text_unknown_chat_type(self, client, mock_http_client):
        """Test send_text() raises on unknown chat type."""
        client.setup(mock_http_client)

        with pytest.raises(RuntimeError, match="(Unknown chat_type|send_text failed)"):
            await client.send_text("unknown", "chat_123", "Test", retries=1)

    async def test_send_typing(self, client, mock_http_client):
        """Test send_typing() sends typing indicator."""
        client.setup(mock_http_client)

        with patch.object(
            client, "post_c2c_message", return_value={"id": "typing"}
        ) as mock_post:
            await client.send_typing("user_123", "msg_original")

        mock_post.assert_called_once()
        msg = mock_post.call_args[0][1]
        assert msg.msg_type == QQMessageType.INPUT_NOTIFY

    async def test_send_typing_error_suppressed(self, client, mock_http_client):
        """Test send_typing() suppresses errors (fire-and-forget)."""
        client.setup(mock_http_client)

        with patch.object(client, "post_c2c_message", side_effect=Exception("Error")):
            # Should not raise
            await client.send_typing("user_123", "msg_123")


# ── Run Tests ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
