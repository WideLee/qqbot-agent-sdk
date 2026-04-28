# -*- coding: utf-8 -*-
"""Unit tests for constants module.

Tests cover:
- SDKConfig dataclass defaults and custom values
- qr_url_template() method
- configure() function
- Module-level constants
"""



from qqbot_agent_sdk.constants import (
    API_BASE,
    DEFAULT_API_TIMEOUT,
    DEDUP_MAX_SIZE,
    DEDUP_WINDOW_SECONDS,
    FILE_UPLOAD_TIMEOUT,
    MAX_MESSAGE_LENGTH,
    MEDIA_TYPE_FILE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VOICE,
    MSG_TYPE_MARKDOWN,
    MSG_TYPE_MEDIA,
    MSG_TYPE_TEXT,
    PORTAL_HOST,
    QQBOT_VERSION,
    SDKConfig,
    TOKEN_URL,
    configure,
    sdk_config,
)


# ---------------------------------------------------------------------------
# SDKConfig Tests
# ---------------------------------------------------------------------------

def test_sdk_config_defaults():
    """Test SDKConfig default values."""
    config = SDKConfig()

    assert config.source == ""
    assert config.extra_ua_items == []


def test_sdk_config_custom_values():
    """Test SDKConfig with custom values."""
    config = SDKConfig(
        source="my-app",
        extra_ua_items=["Hermes/0.9.0", "Production"],
    )

    assert config.source == "my-app"
    assert config.extra_ua_items == ["Hermes/0.9.0", "Production"]


def test_sdk_config_equality():
    """Test SDKConfig equality comparison (dataclass)."""
    config1 = SDKConfig(source="app1")
    config2 = SDKConfig(source="app1")
    config3 = SDKConfig(source="app2")

    assert config1 == config2
    assert config1 != config3


def test_sdk_config_repr():
    """Test SDKConfig string representation."""
    config = SDKConfig(source="test-app", extra_ua_items=["v1"])

    repr_str = repr(config)
    assert "SDKConfig" in repr_str
    assert "test-app" in repr_str


# ---------------------------------------------------------------------------
# qr_url_template Tests
# ---------------------------------------------------------------------------

def test_qr_url_template_without_source():
    """Test qr_url_template without source (default empty)."""
    config = SDKConfig()

    url = config.qr_url_template()

    assert "{task_id}" in url
    assert "source=" not in url
    assert "q.qq.com" in url


def test_qr_url_template_with_source():
    """Test qr_url_template with source parameter."""
    config = SDKConfig(source="my-app")

    url = config.qr_url_template()

    assert "{task_id}" in url
    assert "source=my-app" in url


def test_qr_url_template_format_task_id():
    """Test qr_url_template can be formatted with task_id."""
    config = SDKConfig(source="test")

    url = config.qr_url_template().format(task_id="task123")

    assert "task123" in url
    assert "{task_id}" not in url
    assert "source=test" in url


def test_qr_url_template_no_source_format():
    """Test qr_url_template without source formats correctly."""
    config = SDKConfig()

    url = config.qr_url_template().format(task_id="abc-123")

    assert "abc-123" in url
    assert "source=" not in url


def test_qr_url_template_special_source():
    """Test qr_url_template with special characters in source."""
    config = SDKConfig(source="my app+v2")

    url = config.qr_url_template()

    assert "source=my app+v2" in url


# ---------------------------------------------------------------------------
# configure() Tests
# ---------------------------------------------------------------------------

def test_configure_source():
    """Test configure sets source on sdk_config."""
    original = sdk_config.source
    try:
        configure(source="new-source")
        assert sdk_config.source == "new-source"
    finally:
        sdk_config.source = original


def test_configure_extra_ua_items():
    """Test configure sets extra_ua_items on sdk_config."""
    original = sdk_config.extra_ua_items[:]
    try:
        configure(extra_ua_items=["MyApp/1.0", "Production"])
        assert sdk_config.extra_ua_items == ["MyApp/1.0", "Production"]
    finally:
        sdk_config.extra_ua_items = original


def test_configure_all_parameters():
    """Test configure with all parameters."""
    original_source = sdk_config.source
    original_ua = sdk_config.extra_ua_items[:]
    try:
        configure(source="full-test", extra_ua_items=["v1"])
        assert sdk_config.source == "full-test"
        assert sdk_config.extra_ua_items == ["v1"]
    finally:
        sdk_config.source = original_source
        sdk_config.extra_ua_items = original_ua


def test_configure_none_preserves_values():
    """Test configure with None values preserves existing settings."""
    original_source = sdk_config.source
    original_ua = sdk_config.extra_ua_items[:]
    try:
        configure(source="keep-this", extra_ua_items=["keep"])
        configure()  # No arguments → values unchanged
        assert sdk_config.source == "keep-this"
        assert sdk_config.extra_ua_items == ["keep"]
    finally:
        sdk_config.source = original_source
        sdk_config.extra_ua_items = original_ua


def test_configure_source_only():
    """Test configure with only source parameter."""
    original_source = sdk_config.source
    original_ua = sdk_config.extra_ua_items[:]
    try:
        configure(extra_ua_items=["preserved"])
        configure(source="new")
        assert sdk_config.source == "new"
        assert sdk_config.extra_ua_items == ["preserved"]
    finally:
        sdk_config.source = original_source
        sdk_config.extra_ua_items = original_ua


def test_configure_extra_ua_only():
    """Test configure with only extra_ua_items parameter."""
    original_source = sdk_config.source
    original_ua = sdk_config.extra_ua_items[:]
    try:
        configure(source="preserved")
        configure(extra_ua_items=["new-ua"])
        assert sdk_config.source == "preserved"
        assert sdk_config.extra_ua_items == ["new-ua"]
    finally:
        sdk_config.source = original_source
        sdk_config.extra_ua_items = original_ua


def test_configure_empty_source():
    """Test configure with empty source clears it."""
    original = sdk_config.source
    try:
        configure(source="has-value")
        configure(source="")
        assert sdk_config.source == ""
    finally:
        sdk_config.source = original


def test_configure_empty_ua_list():
    """Test configure with empty list clears extra_ua_items."""
    original = sdk_config.extra_ua_items[:]
    try:
        configure(extra_ua_items=["something"])
        configure(extra_ua_items=[])
        assert sdk_config.extra_ua_items == []
    finally:
        sdk_config.extra_ua_items = original


# ---------------------------------------------------------------------------
# Module-level Constants Tests
# ---------------------------------------------------------------------------

def test_version_string():
    """Test QQBOT_VERSION is a non-empty string."""
    assert isinstance(QQBOT_VERSION, str)
    assert QQBOT_VERSION


def test_api_base_is_https():
    """Test API_BASE is an HTTPS URL."""
    assert API_BASE.startswith("https://")


def test_token_url_is_https():
    """Test TOKEN_URL is an HTTPS URL."""
    assert TOKEN_URL.startswith("https://")


def test_media_type_constants():
    """Test media type constants have expected values."""
    assert MEDIA_TYPE_IMAGE == 1
    assert MEDIA_TYPE_VIDEO == 2
    assert MEDIA_TYPE_VOICE == 3
    assert MEDIA_TYPE_FILE == 4


def test_msg_type_constants():
    """Test message type constants have expected values."""
    assert MSG_TYPE_TEXT == 0
    assert MSG_TYPE_MARKDOWN == 2
    assert MSG_TYPE_MEDIA == 7


def test_timeout_constants():
    """Test timeout constants are positive."""
    assert DEFAULT_API_TIMEOUT > 0
    assert FILE_UPLOAD_TIMEOUT > 0
    assert FILE_UPLOAD_TIMEOUT > DEFAULT_API_TIMEOUT


def test_message_limit_constants():
    """Test message limit constants are positive."""
    assert MAX_MESSAGE_LENGTH > 0
    assert DEDUP_WINDOW_SECONDS > 0
    assert DEDUP_MAX_SIZE > 0


def test_portal_host_default():
    """Test PORTAL_HOST default value."""
    assert PORTAL_HOST  # Not empty
