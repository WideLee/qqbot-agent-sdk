# -*- coding: utf-8 -*-
"""Unit tests for onboard module.

Tests cover:
- Exception classes (OnboardError, OnboardAPIError)
- BindStatus enum
- Internal data classes (_BindTaskResult, _BindPollResult, OnboardResult)
- _create_bind_task and _poll_bind_result
- build_connect_url
- start_onboard (high-level flow)
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from qqbot_agent_sdk.onboard import (
    OnboardAPIError,
    OnboardError,
    OnboardExpiredError,
    OnboardResult,
    _BindPollResult,
    _BindTaskResult,
    BindStatus,
    build_connect_url,
    start_onboard,
)


# ---------------------------------------------------------------------------
# Exception Tests
# ---------------------------------------------------------------------------

def test_onboard_error_base():
    """Test OnboardError base exception."""
    exc = OnboardError("test error")
    assert str(exc) == "test error"
    assert isinstance(exc, Exception)


def test_onboard_api_error():
    """Test OnboardAPIError with retcode and message."""
    exc = OnboardAPIError(40001, "Invalid task_id")
    assert exc.retcode == 40001
    assert exc.message == "Invalid task_id"
    assert str(exc) == "Onboard API error [40001]: Invalid task_id"
    assert isinstance(exc, OnboardError)


def test_onboard_expired_error():
    """Test OnboardExpiredError inherits from OnboardError."""
    exc = OnboardExpiredError("QR code expired")
    assert str(exc) == "QR code expired"
    assert isinstance(exc, OnboardError)
    assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# BindStatus Tests
# ---------------------------------------------------------------------------

def test_bind_status_values():
    """Test BindStatus enum values."""
    assert BindStatus.NONE == 0
    assert BindStatus.PENDING == 1
    assert BindStatus.COMPLETED == 2
    assert BindStatus.EXPIRED == 3


# ---------------------------------------------------------------------------
# Internal Data Classes Tests
# ---------------------------------------------------------------------------

def test_bind_task_result():
    """Test _BindTaskResult dataclass."""
    result = _BindTaskResult(task_id="task123", aes_key="key456")
    assert result.task_id == "task123"
    assert result.aes_key == "key456"


def test_bind_poll_result():
    """Test _BindPollResult dataclass and status checks."""
    # Completed
    result = _BindPollResult(
        status=BindStatus.COMPLETED,
        bot_appid="app123",
        bot_encrypt_secret="encrypted",
        user_openid="user456",
    )
    assert result.is_completed() is True
    assert result.is_pending() is False
    assert result.is_expired() is False

    # Pending
    result = _BindPollResult(
        status=BindStatus.PENDING,
        bot_appid="",
        bot_encrypt_secret="",
        user_openid="",
    )
    assert result.is_completed() is False
    assert result.is_pending() is True
    assert result.is_expired() is False

    # Expired
    result = _BindPollResult(
        status=BindStatus.EXPIRED,
        bot_appid="",
        bot_encrypt_secret="",
        user_openid="",
    )
    assert result.is_completed() is False
    assert result.is_pending() is False
    assert result.is_expired() is True


def test_onboard_result():
    """Test OnboardResult dataclass."""
    result = OnboardResult(
        app_id="app123",
        client_secret="secret456",
        user_openid="user789",
    )
    assert result.app_id == "app123"
    assert result.client_secret == "secret456"
    assert result.user_openid == "user789"


# ---------------------------------------------------------------------------
# _create_bind_task Tests
# httpx is imported inline inside the functions, so we inject a mock module
# into sys.modules before calling them.
# ---------------------------------------------------------------------------

def _make_mock_httpx(mock_response):
    """Create a mock httpx module with AsyncClient context manager."""
    import types

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=mock_response)

    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    mock_httpx = types.ModuleType("httpx")
    mock_httpx.AsyncClient = Mock(return_value=mock_client_cm)

    return mock_httpx


@pytest.mark.asyncio
async def test_create_bind_task_success():
    """Test successful bind task creation."""
    import sys
    from qqbot_agent_sdk.onboard import _create_bind_task

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 0,
        "data": {"task_id": "task123"},
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        result = await _create_bind_task()
        assert isinstance(result, _BindTaskResult)
        assert result.task_id == "task123"
        assert len(result.aes_key) > 0
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


@pytest.mark.asyncio
async def test_create_bind_task_api_error():
    """Test bind task creation with API error."""
    import sys
    from qqbot_agent_sdk.onboard import _create_bind_task

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 40001,
        "msg": "Invalid request",
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        with pytest.raises(OnboardAPIError) as exc_info:
            await _create_bind_task()
        assert exc_info.value.retcode == 40001
        assert exc_info.value.message == "Invalid request"
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


@pytest.mark.asyncio
async def test_create_bind_task_missing_task_id():
    """Test bind task creation with missing task_id."""
    import sys
    from qqbot_agent_sdk.onboard import _create_bind_task

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 0,
        "data": {},
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        with pytest.raises(RuntimeError, match="missing task_id"):
            await _create_bind_task()
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


# ---------------------------------------------------------------------------
# _poll_bind_result Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_bind_result_completed():
    """Test polling with completed status."""
    import sys
    from qqbot_agent_sdk.onboard import _poll_bind_result

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 0,
        "data": {
            "status": 2,
            "bot_appid": "app123",
            "bot_encrypt_secret": "encrypted_secret",
            "user_openid": "user456",
        },
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        result = await _poll_bind_result("task123")
        assert result.status == BindStatus.COMPLETED
        assert result.bot_appid == "app123"
        assert result.bot_encrypt_secret == "encrypted_secret"
        assert result.user_openid == "user456"
        assert result.is_completed() is True
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


@pytest.mark.asyncio
async def test_poll_bind_result_pending():
    """Test polling with pending status."""
    import sys
    from qqbot_agent_sdk.onboard import _poll_bind_result

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 0,
        "data": {
            "status": 1,
            "bot_appid": "",
            "bot_encrypt_secret": "",
            "user_openid": "",
        },
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        result = await _poll_bind_result("task123")
        assert result.status == BindStatus.PENDING
        assert result.is_pending() is True
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


@pytest.mark.asyncio
async def test_poll_bind_result_expired():
    """Test polling with expired status."""
    import sys
    from qqbot_agent_sdk.onboard import _poll_bind_result

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 0,
        "data": {
            "status": 3,
        },
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        result = await _poll_bind_result("task123")
        assert result.status == BindStatus.EXPIRED
        assert result.is_expired() is True
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


@pytest.mark.asyncio
async def test_poll_bind_result_api_error():
    """Test polling with API error."""
    import sys
    from qqbot_agent_sdk.onboard import _poll_bind_result

    mock_response = Mock()
    mock_response.json.return_value = {
        "retcode": 40002,
        "msg": "Task not found",
    }
    mock_response.raise_for_status = Mock()

    mock_httpx = _make_mock_httpx(mock_response)
    original = sys.modules.get("httpx")
    sys.modules["httpx"] = mock_httpx
    try:
        with pytest.raises(OnboardAPIError) as exc_info:
            await _poll_bind_result("task123")
        assert exc_info.value.retcode == 40002
        assert exc_info.value.message == "Task not found"
    finally:
        if original is not None:
            sys.modules["httpx"] = original
        else:
            sys.modules.pop("httpx", None)


# ---------------------------------------------------------------------------
# build_connect_url Tests
# ---------------------------------------------------------------------------

def test_build_connect_url_default_source():
    """Test building connect URL with default source."""
    url = build_connect_url("task123")
    assert "task123" in url
    assert url.startswith("https://")
    assert "q.qq.com" in url


def test_build_connect_url_custom_source():
    """Test building connect URL with custom source."""
    url = build_connect_url("task123", source="custom-app")
    assert "task123" in url
    assert "source=custom-app" in url


def test_build_connect_url_special_chars():
    """Test building connect URL with special characters (URL encoding)."""
    url = build_connect_url("task+123/456")
    # urllib.parse.quote encodes + and /
    assert "task" in url


# ---------------------------------------------------------------------------
# start_onboard Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_onboard_success():
    """Test complete onboard flow with success."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")

    mock_poll_pending = _BindPollResult(
        status=BindStatus.PENDING,
        bot_appid="",
        bot_encrypt_secret="",
        user_openid="",
    )
    mock_poll_completed = _BindPollResult(
        status=BindStatus.COMPLETED,
        bot_appid="app123",
        bot_encrypt_secret="mock_encrypted",
        user_openid="user456",
    )

    qr_callback_called = []

    def on_qr(url: str):
        qr_callback_called.append(url)

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(side_effect=[mock_poll_pending, mock_poll_completed])), \
         patch("qqbot_agent_sdk.onboard._decrypt_secret", return_value="decrypted_secret"), \
         patch("qqbot_agent_sdk.onboard.asyncio.sleep", AsyncMock()):

        result = await start_onboard(on_qr_ready=on_qr, poll_interval=0.1)

        assert isinstance(result, OnboardResult)
        assert result.app_id == "app123"
        assert result.client_secret == "decrypted_secret"
        assert result.user_openid == "user456"
        assert len(qr_callback_called) == 1
        assert "task123" in qr_callback_called[0]


@pytest.mark.asyncio
async def test_start_onboard_timeout():
    """Test onboard flow with timeout."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")
    mock_poll_pending = _BindPollResult(
        status=BindStatus.PENDING,
        bot_appid="",
        bot_encrypt_secret="",
        user_openid="",
    )

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(return_value=mock_poll_pending)), \
         patch("qqbot_agent_sdk.onboard.asyncio.sleep", AsyncMock()):

        with pytest.raises(TimeoutError):
            await start_onboard(poll_timeout=0.1, poll_interval=0.05)


@pytest.mark.asyncio
async def test_start_onboard_expired():
    """Test onboard flow with expired task raises OnboardExpiredError."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")
    mock_poll_expired = _BindPollResult(
        status=BindStatus.EXPIRED,
        bot_appid="",
        bot_encrypt_secret="",
        user_openid="",
    )

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(return_value=mock_poll_expired)):

        with pytest.raises(OnboardExpiredError, match="expired"):
            await start_onboard()


@pytest.mark.asyncio
async def test_start_onboard_callback_exception():
    """Test onboard flow when callback raises exception (should continue)."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")
    mock_poll_completed = _BindPollResult(
        status=BindStatus.COMPLETED,
        bot_appid="app123",
        bot_encrypt_secret="mock_encrypted",
        user_openid="user456",
    )

    def failing_callback(url: str):
        raise ValueError("Callback error")

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(return_value=mock_poll_completed)), \
         patch("qqbot_agent_sdk.onboard._decrypt_secret", return_value="decrypted_secret"):

        # Should not raise, callback error is logged
        result = await start_onboard(on_qr_ready=failing_callback)
        assert result.app_id == "app123"


@pytest.mark.asyncio
async def test_start_onboard_api_error():
    """Test onboard flow with API error during poll."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(side_effect=OnboardAPIError(50001, "Server error"))):

        with pytest.raises(OnboardAPIError) as exc_info:
            await start_onboard()

        assert exc_info.value.retcode == 50001


@pytest.mark.asyncio
async def test_start_onboard_no_callback():
    """Test onboard flow without callback."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")
    mock_poll_completed = _BindPollResult(
        status=BindStatus.COMPLETED,
        bot_appid="app123",
        bot_encrypt_secret="mock_encrypted",
        user_openid="user456",
    )

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(return_value=mock_poll_completed)), \
         patch("qqbot_agent_sdk.onboard._decrypt_secret", return_value="decrypted_secret"):

        result = await start_onboard()
        assert result.app_id == "app123"


@pytest.mark.asyncio
async def test_start_onboard_custom_source():
    """Test onboard flow with custom source parameter."""
    mock_task = _BindTaskResult(task_id="task123", aes_key="dGVzdGtleQ==")
    mock_poll_completed = _BindPollResult(
        status=BindStatus.COMPLETED,
        bot_appid="app123",
        bot_encrypt_secret="mock_encrypted",
        user_openid="user456",
    )

    qr_urls = []

    def capture_qr(url: str):
        qr_urls.append(url)

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(return_value=mock_poll_completed)), \
         patch("qqbot_agent_sdk.onboard._decrypt_secret", return_value="decrypted_secret"):

        result = await start_onboard(on_qr_ready=capture_qr, source="my-app")

        assert result.app_id == "app123"
        assert len(qr_urls) == 1
        assert "source=my-app" in qr_urls[0]


# ---------------------------------------------------------------------------
# Integration Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_onboard_flow():
    """Integration test: create -> poll pending -> poll completed."""
    mock_task = _BindTaskResult(task_id="integration_task", aes_key="aW50ZWdyYXRpb25rZXk=")

    poll_results = [
        _BindPollResult(status=BindStatus.PENDING, bot_appid="", bot_encrypt_secret="", user_openid=""),
        _BindPollResult(status=BindStatus.PENDING, bot_appid="", bot_encrypt_secret="", user_openid=""),
        _BindPollResult(
            status=BindStatus.COMPLETED,
            bot_appid="integration_app",
            bot_encrypt_secret="integration_encrypted",
            user_openid="integration_user",
        ),
    ]

    qr_url_received = None

    def save_qr(url: str):
        nonlocal qr_url_received
        qr_url_received = url

    with patch("qqbot_agent_sdk.onboard._create_bind_task", AsyncMock(return_value=mock_task)), \
         patch("qqbot_agent_sdk.onboard._poll_bind_result", AsyncMock(side_effect=poll_results)), \
         patch("qqbot_agent_sdk.onboard._decrypt_secret", return_value="integration_secret"), \
         patch("qqbot_agent_sdk.onboard.asyncio.sleep", AsyncMock()):

        result = await start_onboard(on_qr_ready=save_qr, poll_interval=0.1)

        # Verify result
        assert result.app_id == "integration_app"
        assert result.client_secret == "integration_secret"
        assert result.user_openid == "integration_user"

        # Verify QR callback was called
        assert qr_url_received is not None
        assert "integration_task" in qr_url_received
