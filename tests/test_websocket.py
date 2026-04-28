# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.websocket module.

Tests cover:
- WebSocket lifecycle (open, start_listeners, stop)
- Connection and reconnection logic
- Heartbeat mechanism
- Message deduplication
- Payload dispatch (Hello, Ready, Resumed, Dispatch)
- Error handling and close code classification
- Thread safety (dedup cache)
- Resource cleanup
- Quick disconnect detection
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qqbot_agent_sdk.constants import (
    DEDUP_MAX_SIZE,
    DEDUP_WINDOW_SECONDS,
    MAX_QUICK_DISCONNECT_COUNT,
    QUICK_DISCONNECT_THRESHOLD,
    RECONNECT_BACKOFF,
)
from qqbot_agent_sdk.dto import EventType, OPCode
from qqbot_agent_sdk.websocket import QQCloseError, QQWebSocket, WSCallbacks


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_callbacks():
    """Create mock callbacks for testing."""
    return WSCallbacks(
        on_message_event=AsyncMock(),
        on_connected=Mock(),
        on_disconnected=Mock(),
        on_fatal_error=Mock(),
        get_token=Mock(return_value="test_token"),
        get_session=Mock(return_value=(None, None)),
        set_session=Mock(),
        set_heartbeat_interval=Mock(),
        clear_token=Mock(),
        fail_pending=Mock(),
        get_gateway_url=Mock(return_value="wss://test.example.com/gateway"),
        on_interaction_event=None,
        on_ready=None,
        on_heartbeat_ack=None,
    )


@pytest.fixture
def websocket(mock_callbacks):
    """Create a QQWebSocket instance for testing."""
    return QQWebSocket(callbacks=mock_callbacks, log_tag="TestBot")


@pytest.fixture
def mock_aiohttp_session():
    """Create a mock aiohttp ClientSession."""
    session = Mock()
    ws = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    ws.receive = AsyncMock()
    ws.send_json = AsyncMock()
    session.ws_connect = AsyncMock(return_value=ws)
    return session, ws


# ── QQCloseError Tests ────────────────────────────────────────────────────


def test_qq_close_error_with_code():
    """Test QQCloseError initialization with code and reason."""
    exc = QQCloseError(4001, "Authentication failed")
    assert exc.code == 4001
    assert exc.reason == "Authentication failed"
    assert "4001" in str(exc)
    assert "Authentication failed" in str(exc)


def test_qq_close_error_without_code():
    """Test QQCloseError with None code."""
    exc = QQCloseError(None, "Unknown error")
    assert exc.code is None
    assert exc.reason == "Unknown error"


def test_qq_close_error_type_conversion():
    """Test QQCloseError converts code to int."""
    exc = QQCloseError("4002", None)
    assert exc.code == 4002
    assert exc.reason == ""


# ── Initialization Tests ──────────────────────────────────────────────────


def test_websocket_initialization(websocket, mock_callbacks):
    """Test QQWebSocket initialization."""
    assert websocket._cb is mock_callbacks
    assert websocket._log_tag == "TestBot"
    assert websocket._ws is None
    assert websocket._session is None
    assert websocket._running is False
    assert websocket._stop_requested is False
    assert websocket._heartbeat_interval == 30.0
    assert websocket._listen_task is None
    assert websocket._heartbeat_task is None
    assert websocket._ws_loop is None
    assert websocket._ws_thread is None
    assert websocket._main_loop is None
    assert isinstance(websocket._seen_msg_ids, dict)
    assert len(websocket._seen_msg_ids) == 0
    assert hasattr(websocket, "_seen_lock")
    assert websocket._seen_lock is not None


# ── Open Connection Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_connection_success(websocket, mock_aiohttp_session):
    """Test successful WebSocket connection."""
    session, ws = mock_aiohttp_session
    
    await websocket.open("wss://test.example.com/gateway", session)
    
    assert websocket._session is session
    assert websocket._ws is ws
    session.ws_connect.assert_called_once()
    call_args = session.ws_connect.call_args
    assert call_args[0][0] == "wss://test.example.com/gateway"
    assert "User-Agent" in call_args[1]["headers"]


@pytest.mark.asyncio
async def test_open_connection_closes_existing(websocket, mock_aiohttp_session):
    """Test opening a new connection closes the existing one."""
    session, ws = mock_aiohttp_session
    
    # First connection
    await websocket.open("wss://test1.example.com", session)
    old_ws = websocket._ws
    
    # Second connection (should close first)
    new_ws = AsyncMock()
    new_ws.closed = False
    session.ws_connect.return_value = new_ws
    
    await websocket.open("wss://test2.example.com", session)
    
    old_ws.close.assert_called_once()
    assert websocket._ws is new_ws


@pytest.mark.asyncio
async def test_open_connection_stores_session_before_connect(websocket, mock_aiohttp_session):
    """Test that session is stored even if ws_connect fails."""
    session, _ = mock_aiohttp_session
    session.ws_connect.side_effect = Exception("Connection failed")
    
    with pytest.raises(Exception, match="Connection failed"):
        await websocket.open("wss://test.example.com", session)
    
    # Session should still be stored (for reconnect)
    assert websocket._session is session


# ── Start/Stop Listeners Tests ────────────────────────────────────────────


def test_start_listeners(websocket):
    """Test starting listen and heartbeat tasks."""
    def _mock_create_task(coro):
        """Close the coroutine and return a mock task."""
        coro.close()
        return Mock()

    with patch("asyncio.create_task", side_effect=_mock_create_task) as mock_create_task:
        websocket.start_listeners()
        
        assert websocket._running is True
        assert websocket._stop_requested is False
        assert mock_create_task.call_count == 2
        assert websocket._listen_task is not None
        assert websocket._heartbeat_task is not None


@pytest.mark.asyncio
async def test_stop_async_cancels_tasks(websocket):
    """Test _stop_async cancels all tasks."""
    # Setup mock tasks — use Mock() because asyncio.Task.cancel() is synchronous.
    # Add __await__ returning CancelledError so ``await task`` behaves like a real
    # cancelled task.
    def _cancelled_await(self):
        raise asyncio.CancelledError()
        yield  # noqa: F841 — unreachable, makes this a generator for __await__

    mock_listen = Mock()
    mock_listen.__await__ = _cancelled_await
    mock_heartbeat = Mock()
    mock_heartbeat.__await__ = _cancelled_await
    websocket._listen_task = mock_listen
    websocket._heartbeat_task = mock_heartbeat
    
    # Setup mock WebSocket
    mock_ws = AsyncMock()
    mock_ws.closed = False
    websocket._ws = mock_ws
    
    await websocket._stop_async()
    
    # Verify tasks were cancelled
    mock_listen.cancel.assert_called_once()
    mock_heartbeat.cancel.assert_called_once()
    
    # Verify WebSocket was closed
    mock_ws.close.assert_called_once()
    
    # Verify state reset
    assert websocket._running is False
    assert websocket._stop_requested is True
    assert websocket._listen_task is None
    assert websocket._heartbeat_task is None
    assert websocket._ws is None


# ── JSON Parsing Tests ────────────────────────────────────────────────────


def test_parse_json_success(websocket):
    """Test successful JSON parsing."""
    raw = '{"op": 10, "d": {"heartbeat_interval": 41250}}'
    result = websocket._parse_json(raw)
    
    assert result == {"op": 10, "d": {"heartbeat_interval": 41250}}


def test_parse_json_invalid_json(websocket):
    """Test parsing invalid JSON returns None."""
    raw = '{"op": 10, invalid json'
    result = websocket._parse_json(raw)
    
    assert result is None


def test_parse_json_non_dict(websocket):
    """Test parsing non-dict JSON returns None."""
    raw = '["not", "a", "dict"]'
    result = websocket._parse_json(raw)
    
    assert result is None


def test_parse_json_null(websocket):
    """Test parsing null returns None."""
    raw = 'null'
    result = websocket._parse_json(raw)
    
    assert result is None


# ── Message Deduplication Tests ───────────────────────────────────────────


def test_is_duplicate_first_time(websocket):
    """Test message is not duplicate on first occurrence."""
    msg_id = "test_msg_123"
    
    is_dup = websocket._is_duplicate(msg_id)
    
    assert is_dup is False
    assert msg_id in websocket._seen_msg_ids


def test_is_duplicate_second_time(websocket):
    """Test message is duplicate on second occurrence."""
    msg_id = "test_msg_123"
    
    websocket._is_duplicate(msg_id)
    is_dup = websocket._is_duplicate(msg_id)
    
    assert is_dup is True


def test_is_duplicate_thread_safe(websocket):
    """Test message deduplication is thread-safe."""
    results = []
    
    def check_duplicate():
        for i in range(100):
            msg_id = f"msg_{i % 10}"
            is_dup = websocket._is_duplicate(msg_id)
            results.append(is_dup)
    
    # Run from multiple threads
    threads = [threading.Thread(target=check_duplicate) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Should have exactly 10 False (first occurrences)
    assert results.count(False) == 10


def test_evict_seen_ids_time_based(websocket):
    """Test eviction removes old entries."""
    now = time.time()
    
    # Add old entries
    websocket._seen_msg_ids = {
        "old1": now - DEDUP_WINDOW_SECONDS - 10,
        "old2": now - DEDUP_WINDOW_SECONDS - 5,
        "recent": now - 10,
    }
    
    websocket._evict_seen_ids(now)
    
    assert "old1" not in websocket._seen_msg_ids
    assert "old2" not in websocket._seen_msg_ids
    assert "recent" in websocket._seen_msg_ids


def test_evict_seen_ids_force_eviction(websocket):
    """Test force eviction when cache exceeds limit."""
    now = time.time()
    
    # Add DEDUP_MAX_SIZE entries (all very recent, within window)
    websocket._seen_msg_ids = {
        f"msg_{i}": now - i for i in range(DEDUP_MAX_SIZE)
    }
    
    websocket._evict_seen_ids(now)
    
    # Time-based eviction will remove old entries first
    # Only entries within DEDUP_WINDOW_SECONDS will remain
    remaining = [i for i in range(DEDUP_MAX_SIZE) if i < DEDUP_WINDOW_SECONDS]
    
    # If still over limit after time-based eviction, force eviction kicks in
    if len(remaining) >= DEDUP_MAX_SIZE:
        expected_size = DEDUP_MAX_SIZE // 2
    else:
        expected_size = len(remaining)
    
    assert len(websocket._seen_msg_ids) == expected_size
    
    # Most recent entries should be kept
    assert "msg_0" in websocket._seen_msg_ids
    assert "msg_1" in websocket._seen_msg_ids


# ── Payload Dispatch Tests ────────────────────────────────────────────────


def test_dispatch_payload_updates_sequence(websocket, mock_callbacks):
    """Test sequence number is updated on valid payload."""
    mock_callbacks.get_session.return_value = ("session_123", 5)
    
    payload = {"op": 0, "s": 10, "t": "MESSAGE_CREATE", "d": {}}
    
    websocket._dispatch_payload(payload)
    
    mock_callbacks.set_session.assert_called_with("session_123", 10)


def test_dispatch_payload_skips_lower_sequence(websocket, mock_callbacks):
    """Test lower sequence number is not updated."""
    mock_callbacks.get_session.return_value = ("session_123", 10)
    
    payload = {"op": 0, "s": 5, "t": "MESSAGE_CREATE", "d": {}}
    
    websocket._dispatch_payload(payload)
    
    # Should not update to lower sequence
    mock_callbacks.set_session.assert_not_called()


def test_handle_hello_schedules_identify(websocket, mock_callbacks):
    """Test Hello triggers Identify when no session exists."""
    mock_callbacks.get_session.return_value = (None, None)
    
    data = {"heartbeat_interval": 41250}
    
    def _close_coro(coro):
        """Close the coroutine to prevent 'never awaited' warning."""
        coro.close()
        return None

    with patch.object(websocket, "_create_task", side_effect=_close_coro) as mock_create:
        websocket._handle_hello(data)
    
    assert websocket._heartbeat_interval == 41250 / 1000.0 * 0.8
    mock_callbacks.set_heartbeat_interval.assert_called_once()
    mock_create.assert_called_once()


def test_handle_hello_schedules_resume(websocket, mock_callbacks):
    """Test Hello triggers Resume when session exists."""
    mock_callbacks.get_session.return_value = ("session_123", 100)
    
    data = {"heartbeat_interval": 41250}
    
    def _close_coro(coro):
        """Close the coroutine to prevent 'never awaited' warning."""
        coro.close()
        return None

    with patch.object(websocket, "_create_task", side_effect=_close_coro) as mock_create:
        websocket._handle_hello(data)
    
    mock_create.assert_called_once()


def test_handle_dispatch_ready(websocket, mock_callbacks):
    """Test READY event handling preserves existing seq."""
    # _dispatch_payload has already updated seq from payload.s before
    # calling _handle_dispatch, so get_session returns (old_session, updated_seq).
    mock_callbacks.get_session.return_value = ("old_session", 5)

    data = {
        "session_id": "new_session_123",
        "user": {"id": "bot_123", "username": "TestBot"},
        "shard": [0, 1],
    }
    
    websocket._handle_dispatch(EventType.READY, data)
    
    # Should preserve the existing seq (5), not reset to None
    mock_callbacks.set_session.assert_called_with("new_session_123", 5)
    mock_callbacks.on_connected.assert_called_once()


def test_handle_dispatch_resumed(websocket, mock_callbacks):
    """Test RESUMED event handling."""
    mock_callbacks.get_session.return_value = ("session_123", 100)
    
    websocket._handle_dispatch(EventType.RESUMED, {})
    
    mock_callbacks.on_connected.assert_called_once()


def test_handle_dispatch_message_event(websocket, mock_callbacks):
    """Test message event handling."""
    data = {"id": "msg_123", "content": "Hello"}
    
    with patch.object(websocket, "_dispatch_to_main") as mock_dispatch:
        # Use a valid message event type from MESSAGE_EVENT_TYPES
        websocket._handle_dispatch(EventType.C2C_MESSAGE_CREATE, data)
    
    # Should have called _dispatch_to_main with a coroutine
    mock_dispatch.assert_called_once()
    # The coroutine should be on_message_event
    call_arg = mock_dispatch.call_args[0][0]
    assert asyncio.iscoroutine(call_arg)
    # Close the coroutine to prevent warning
    call_arg.close()


def test_handle_dispatch_message_duplicate(websocket, mock_callbacks):
    """Test duplicate message is dropped."""
    data = {"id": "msg_123", "content": "Hello"}
    
    # First time
    with patch.object(websocket, "_dispatch_to_main") as mock_dispatch:
        websocket._handle_dispatch(EventType.C2C_MESSAGE_CREATE, data)
        # Close coroutine
        if mock_dispatch.called:
            mock_dispatch.call_args[0][0].close()
    
    # Second time (duplicate)
    with patch.object(websocket, "_dispatch_to_main") as mock_dispatch:
        websocket._handle_dispatch(EventType.C2C_MESSAGE_CREATE, data)
    
    # Should not dispatch duplicate
    mock_dispatch.assert_not_called()


def test_handle_dispatch_interaction_event(websocket, mock_callbacks):
    """Test interaction event handling with callback."""
    mock_callbacks.on_interaction_event = AsyncMock()
    data = {"id": "interaction_123"}
    
    with patch.object(websocket, "_dispatch_to_main") as mock_dispatch:
        websocket._handle_dispatch(EventType.INTERACTION_CREATE, data)
    
    # Should call _dispatch_to_main
    mock_dispatch.assert_called_once()
    # Close coroutine
    mock_dispatch.call_args[0][0].close()


def test_handle_dispatch_interaction_no_callback(websocket, mock_callbacks):
    """Test interaction event is dropped when no callback."""
    mock_callbacks.on_interaction_event = None
    data = {"id": "interaction_123"}
    
    with patch.object(websocket, "_dispatch_to_main") as mock_dispatch:
        websocket._handle_dispatch(EventType.INTERACTION_CREATE, data)
    
    # Should not dispatch
    mock_dispatch.assert_not_called()


# ── Heartbeat Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_heartbeat(websocket, mock_callbacks):
    """Test heartbeat loop sends periodic heartbeats."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    websocket._ws = mock_ws
    websocket._running = True
    websocket._heartbeat_interval = 0.01  # Fast for testing
    mock_callbacks.get_session.return_value = ("session_123", 10)
    
    # Run for short time
    task = asyncio.create_task(websocket._heartbeat_loop())
    await asyncio.sleep(0.05)
    websocket._running = False
    
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
    
    # Should have sent at least one heartbeat
    assert mock_ws.send_json.call_count >= 1
    call_args = mock_ws.send_json.call_args_list[0][0][0]
    assert call_args["op"] == OPCode.HEARTBEAT
    assert call_args["d"] == 10


@pytest.mark.asyncio
async def test_heartbeat_loop_exits_when_ws_closed(websocket):
    """Test heartbeat exits when WebSocket is closed."""
    mock_ws = AsyncMock()
    mock_ws.closed = True
    websocket._ws = mock_ws
    websocket._running = True
    # Shrink the pre-sleep so the loop reaches the closed-check without
    # waiting the default 30s heartbeat interval.
    websocket._heartbeat_interval = 0.0

    await websocket._heartbeat_loop()

    # Should exit immediately without sending
    mock_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_loop_handles_send_failure(websocket, mock_callbacks):
    """Test heartbeat continues after send failure."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.send_json.side_effect = [
        Exception("Network error"),
        None,  # Second attempt succeeds
    ]
    websocket._ws = mock_ws
    websocket._running = True
    websocket._heartbeat_interval = 0.01
    mock_callbacks.get_session.return_value = (None, 0)
    
    task = asyncio.create_task(websocket._heartbeat_loop())
    await asyncio.sleep(0.05)
    websocket._running = False
    
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
    
    # Should have attempted multiple times
    assert mock_ws.send_json.call_count >= 2


# ── Quick Disconnect Tests ────────────────────────────────────────────────


def test_update_quick_count_normal_disconnect(websocket):
    """Test normal disconnect (>5s) resets counter."""
    connect_time = time.monotonic() - 10  # 10 seconds ago
    
    result = websocket._update_quick_count(connect_time, 2)
    
    assert result == 0  # Reset


def test_update_quick_count_quick_disconnect(websocket):
    """Test quick disconnect (<5s) increments counter."""
    connect_time = time.monotonic() - 2  # 2 seconds ago
    
    result = websocket._update_quick_count(connect_time, 1)
    
    assert result == 2  # Incremented


def test_update_quick_count_fatal_threshold(websocket, mock_callbacks):
    """Test fatal threshold triggers error."""
    connect_time = time.monotonic() - 2
    count = MAX_QUICK_DISCONNECT_COUNT - 1
    
    result = websocket._update_quick_count(connect_time, count)
    
    assert result == -1  # Fatal
    assert websocket._stop_requested is True
    mock_callbacks.on_fatal_error.assert_called_once()


def test_update_quick_count_zero_connect_time(websocket):
    """Test zero connect_time is treated as sentinel."""
    result = websocket._update_quick_count(0.0, 2)
    
    assert result == 0  # Reset


# ── Reconnect Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_success(websocket, mock_callbacks, mock_aiohttp_session):
    """Test successful reconnection."""
    session, ws = mock_aiohttp_session
    websocket._session = session
    websocket._heartbeat_interval = 30.0

    # Patch RECONNECT_BACKOFF so the initial pre-reconnect sleep is 0.
    with patch("qqbot_agent_sdk.websocket.RECONNECT_BACKOFF", [0]), \
         patch.object(websocket, "open", new_callable=AsyncMock) as mock_open:
        result = await websocket._reconnect(0)

    assert result is True
    mock_open.assert_called_once()
    mock_callbacks.get_gateway_url.assert_called_once()
    assert websocket._heartbeat_task is not None


@pytest.mark.asyncio
async def test_reconnect_timeout(websocket, mock_callbacks):
    """Test reconnection timeout."""
    websocket._session = Mock()

    async def slow_open(*args):
        # Must sleep longer than the (patched) CONNECT_TIMEOUT_SECONDS * 3
        # so that wait_for triggers a TimeoutError.
        await asyncio.sleep(1.0)

    # Patch both the backoff (pre-reconnect sleep) and CONNECT_TIMEOUT_SECONDS
    # (controls the wait_for timeout, originally 20*3=60s).
    with patch("qqbot_agent_sdk.websocket.RECONNECT_BACKOFF", [0]), \
         patch("qqbot_agent_sdk.websocket.CONNECT_TIMEOUT_SECONDS", 0.01), \
         patch.object(websocket, "open", side_effect=slow_open):
        result = await websocket._reconnect(0)

    assert result is False


@pytest.mark.asyncio
async def test_reconnect_cancels_stale_heartbeat(websocket, mock_callbacks, mock_aiohttp_session):
    """Test reconnection cancels stale heartbeat task."""
    session, ws = mock_aiohttp_session
    websocket._session = session

    # Create a mock task that's still running
    mock_task = Mock()
    mock_task.done.return_value = False
    mock_task.cancel = Mock()
    websocket._heartbeat_task = mock_task

    with patch("qqbot_agent_sdk.websocket.RECONNECT_BACKOFF", [0]), \
         patch.object(websocket, "open", new_callable=AsyncMock), \
         patch("asyncio.create_task"):
        await websocket._reconnect(0)

    # Should have cancelled old task
    mock_task.cancel.assert_called_once()


# ── Close Handling Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_close_action_stop(websocket, mock_callbacks):
    """Test STOP action (fatal error)."""
    result = await websocket._apply_close_action(4915, 0)  # Banned
    
    assert result is False
    assert websocket._stop_requested is True
    mock_callbacks.on_fatal_error.assert_called_once()


@pytest.mark.asyncio
async def test_apply_close_action_rate_limit(websocket):
    """Test RATE_LIMIT action (4008)."""
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await websocket._apply_close_action(4008, 0)
    
    assert result is True
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_apply_close_action_identify_only(websocket, mock_callbacks):
    """Test IDENTIFY_ONLY action (clear session)."""
    # Use 4007 which is IDENTIFY_ONLY
    result = await websocket._apply_close_action(4007, 0)
    
    assert result is True
    mock_callbacks.set_session.assert_called_with(None, None)


@pytest.mark.asyncio
async def test_apply_close_action_resume_ok(websocket, mock_callbacks):
    """Test RESUME_OK action (keep session)."""
    result = await websocket._apply_close_action(1001, 0)
    
    assert result is True
    # Should not clear session
    mock_callbacks.set_session.assert_not_called()


# ── Handle WS Error Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_ws_error_with_close_error(websocket, mock_callbacks):
    """Test handling QQCloseError."""
    exc = QQCloseError(4001, "Authentication failed")
    
    with patch.object(websocket, "_apply_close_action", return_value=True):
        with patch.object(websocket, "_reconnect", return_value=True) as mock_reconnect:
            result = await websocket._handle_ws_error(exc, 0, notify_disconnect=True)
    
    assert result is True
    mock_callbacks.on_disconnected.assert_called_once()
    mock_callbacks.fail_pending.assert_called_once()
    mock_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ws_error_with_generic_error(websocket, mock_callbacks):
    """Test handling generic exception."""
    exc = RuntimeError("Connection lost")
    
    with patch.object(websocket, "_reconnect", return_value=True) as mock_reconnect:
        result = await websocket._handle_ws_error(exc, 0, notify_disconnect=True)
    
    assert result is True
    mock_callbacks.on_disconnected.assert_called_once()
    mock_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handle_ws_error_skip_disconnect_notification(websocket, mock_callbacks):
    """Test skipping disconnect notification on retry."""
    exc = RuntimeError("Connection lost")
    
    with patch.object(websocket, "_reconnect", return_value=True):
        await websocket._handle_ws_error(exc, 0, notify_disconnect=False)
    
    # Should not call on_disconnected
    mock_callbacks.on_disconnected.assert_not_called()


# ── Send WebSocket JSON Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_ws_json_success(websocket):
    """Test successful JSON send."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    websocket._ws = mock_ws
    
    payload = {"op": 2, "d": {"token": "test"}}
    result = await websocket._send_ws_json(payload, "Identify")
    
    assert result is True
    mock_ws.send_json.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_send_ws_json_no_connection(websocket):
    """Test send fails when WebSocket not connected."""
    websocket._ws = None
    
    payload = {"op": 2, "d": {"token": "test"}}
    result = await websocket._send_ws_json(payload, "Identify")
    
    assert result is False


@pytest.mark.asyncio
async def test_send_ws_json_closed_connection(websocket):
    """Test send fails when WebSocket is closed."""
    mock_ws = AsyncMock()
    mock_ws.closed = True
    websocket._ws = mock_ws
    
    payload = {"op": 2, "d": {"token": "test"}}
    result = await websocket._send_ws_json(payload, "Identify")
    
    assert result is False
    mock_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_send_ws_json_send_failure(websocket):
    """Test send handles exception."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.send_json.side_effect = Exception("Network error")
    websocket._ws = mock_ws
    
    payload = {"op": 2, "d": {"token": "test"}}
    result = await websocket._send_ws_json(payload, "Identify")
    
    assert result is False


# ── Send Identify Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_identify(websocket, mock_callbacks):
    """Test sending Identify payload."""
    mock_callbacks.get_token.return_value = "test_token_123"
    
    with patch.object(websocket, "_send_ws_json", return_value=True) as mock_send:
        await websocket._send_identify()
    
    mock_send.assert_called_once()
    payload = mock_send.call_args[0][0]
    assert payload["op"] == OPCode.IDENTIFY
    assert payload["d"]["token"] == "QQBot test_token_123"
    assert "intents" in payload["d"]
    assert "shard" in payload["d"]


# ── Send Resume Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_resume_success(websocket, mock_callbacks):
    """Test sending Resume payload."""
    mock_callbacks.get_token.return_value = "test_token_123"
    mock_callbacks.get_session.return_value = ("session_123", 100)
    
    with patch.object(websocket, "_send_ws_json", return_value=True) as mock_send:
        await websocket._send_resume()
    
    mock_send.assert_called_once()
    payload = mock_send.call_args[0][0]
    assert payload["op"] == OPCode.RESUME
    assert payload["d"]["token"] == "QQBot test_token_123"
    assert payload["d"]["session_id"] == "session_123"
    assert payload["d"]["seq"] == 100


@pytest.mark.asyncio
async def test_send_resume_failure_clears_session(websocket, mock_callbacks):
    """Test Resume failure clears session."""
    mock_callbacks.get_token.return_value = "test_token_123"
    mock_callbacks.get_session.return_value = ("session_123", 100)
    
    with patch.object(websocket, "_send_ws_json", return_value=False):
        await websocket._send_resume()
    
    # Should clear session on failure
    mock_callbacks.set_session.assert_called_with(None, None)


# ── Close WebSocket Async Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_ws_async(websocket):
    """Test async WebSocket close."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    websocket._ws = mock_ws
    
    def _close_coro(coro):
        """Close the coroutine to prevent 'never awaited' warning."""
        coro.close()
        return None

    with patch.object(websocket, "_create_task", side_effect=_close_coro) as mock_create:
        websocket._close_ws_async()
    
    # Should schedule close task
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_close_ws_async_handles_error(websocket):
    """Test async close handles exceptions."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.close.side_effect = Exception("Close error")
    websocket._ws = mock_ws
    
    # Capture the coroutine passed to _create_task and await it directly.
    captured_coro = None

    def _capture_coro(coro):
        nonlocal captured_coro
        captured_coro = coro
        return None

    with patch.object(websocket, "_create_task", side_effect=_capture_coro):
        websocket._close_ws_async()

    # Await the _do_close coroutine — it should handle the exception internally
    assert captured_coro is not None
    await captured_coro  # Should not raise


# ── Create Task Tests ─────────────────────────────────────────────────────


def test_create_task_with_running_loop():
    """Test _create_task with running event loop."""
    async def test_coro():
        return 42
    
    async def run_test():
        task = QQWebSocket._create_task(test_coro())
        assert task is not None
        result = await task
        assert result == 42
    
    asyncio.run(run_test())


def test_create_task_without_loop():
    """Test _create_task without running loop."""
    async def test_coro():
        return 42
    
    coro = test_coro()
    task = QQWebSocket._create_task(coro)
    
    assert task is None
    # Coroutine should be closed to prevent warning


# ── Dispatch to Main Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_to_main_with_main_loop(websocket):
    """Test dispatching to main loop."""
    main_loop = asyncio.get_running_loop()
    websocket._main_loop = main_loop
    
    async def test_coro():
        pass
    
    def _close_and_record(coro, loop):
        """Intercept run_coroutine_threadsafe and close the coroutine."""
        coro.close()

    with patch("asyncio.run_coroutine_threadsafe", side_effect=_close_and_record) as mock_run:
        websocket._dispatch_to_main(test_coro())
    
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_to_main_without_main_loop(websocket):
    """Test fallback when no main loop set."""
    websocket._main_loop = None
    
    async def test_coro():
        return 42
    
    def _close_coro(coro):
        """Close the coroutine to prevent 'never awaited' warning."""
        coro.close()
        return None

    with patch.object(websocket, "_create_task", side_effect=_close_coro) as mock_create:
        websocket._dispatch_to_main(test_coro())
    
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_to_main_closed_loop(websocket):
    """Test handling of closed main loop."""
    mock_loop = Mock()
    mock_loop.is_closed.return_value = False
    websocket._main_loop = mock_loop
    
    async def test_coro():
        return 42
    
    with patch("asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("Loop closed")):
        websocket._dispatch_to_main(test_coro())
    
    # Should not raise exception, coroutine should be closed


# ── Integration Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_lifecycle(websocket, mock_callbacks, mock_aiohttp_session):
    """Test complete WebSocket lifecycle."""
    session, ws = mock_aiohttp_session
    
    # Setup message response
    ws.receive.side_effect = [
        Mock(type=10, data='{"op": 10, "d": {"heartbeat_interval": 41250}}'),  # Hello
        Mock(type=1),  # TEXT
        asyncio.CancelledError(),  # Stop
    ]
    
    # Open connection
    await websocket.open("wss://test.example.com", session)
    assert websocket._ws is ws
    
    # Start listeners
    websocket.start_listeners()
    assert websocket._running is True
    
    # Stop
    await websocket.stop()
    assert websocket._running is False
    assert websocket._ws is None


# ── Edge Cases ────────────────────────────────────────────────────────────


def test_handle_heartbeat_ack_with_callback(websocket, mock_callbacks):
    """Test heartbeat ACK with callback."""
    mock_callbacks.on_heartbeat_ack = Mock()
    
    websocket._handle_heartbeat_ack()
    
    mock_callbacks.on_heartbeat_ack.assert_called_once()


def test_handle_heartbeat_ack_without_callback(websocket, mock_callbacks):
    """Test heartbeat ACK without callback."""
    mock_callbacks.on_heartbeat_ack = None
    
    # Should not raise exception
    websocket._handle_heartbeat_ack()


@pytest.mark.asyncio
async def test_reconnect_with_exponential_backoff(websocket):
    """Test reconnection respects exponential backoff."""
    websocket._session = Mock()
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(websocket, "open", new_callable=AsyncMock):
            await websocket._reconnect(0)
            await websocket._reconnect(1)
            await websocket._reconnect(2)
    
    # Should use increasing delays
    calls = [call[0][0] for call in mock_sleep.call_args_list]
    assert calls[0] == RECONNECT_BACKOFF[0]
    assert calls[1] == RECONNECT_BACKOFF[1]
    assert calls[2] == RECONNECT_BACKOFF[2]


def test_update_quick_count_edge_case_threshold(websocket):
    """Test quick disconnect at exact threshold."""
    connect_time = time.monotonic() - QUICK_DISCONNECT_THRESHOLD
    
    result = websocket._update_quick_count(connect_time, 1)
    
    # At exact threshold, should reset (>=)
    assert result == 0
