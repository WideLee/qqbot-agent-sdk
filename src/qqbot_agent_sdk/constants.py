# -*- coding: utf-8 -*-
"""QQBot adapter constants — API endpoints, timeouts, message limits.

All values are pure data with no external framework dependencies.

Runtime configuration
---------------------
Call :func:`configure` once at startup to customise the SDK-wide ``source``
tag (embedded in QR-code URLs) and an optional extra User-Agent suffix::

    from qqbot_agent_sdk import configure
    configure(source="my-app", extra_ua="my-app/2.0")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError as _PNF
    QQBOT_VERSION: str = _pkg_version("qqbot-agent-sdk")
except _PNF:
    # Package not installed (e.g. running directly from source without `pip install -e .`)
    QQBOT_VERSION = "0.0.0"

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

# Configurable via QQ_PORTAL_HOST for corporate proxies or test environments.
PORTAL_HOST = os.getenv("QQ_PORTAL_HOST", "q.qq.com")

API_BASE = os.getenv("QQ_API_BASE", "https://api.sgroup.qq.com")
TOKEN_URL = os.getenv("QQ_TOKEN_URL", "https://bots.qq.com/app/getAppAccessToken")
GATEWAY_URL_PATH = "/gateway"

# QR-code onboard endpoints (portal host)
ONBOARD_CREATE_PATH = "/lite/create_bind_task"
ONBOARD_POLL_PATH = "/lite/poll_bind_result"

# ---------------------------------------------------------------------------
# Timeouts & retry
# ---------------------------------------------------------------------------

DEFAULT_API_TIMEOUT = 30.0
FILE_UPLOAD_TIMEOUT = 120.0
CONNECT_TIMEOUT_SECONDS = 20.0

RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 10000
RATE_LIMIT_DELAY = 60  # seconds
QUICK_DISCONNECT_THRESHOLD = 5.0  # seconds
MAX_QUICK_DISCONNECT_COUNT = 3

ONBOARD_POLL_INTERVAL = 2.0
ONBOARD_API_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# Message limits
# ---------------------------------------------------------------------------

MAX_MESSAGE_LENGTH = 4000
DEDUP_WINDOW_SECONDS = 300
DEDUP_MAX_SIZE = 1000

# ---------------------------------------------------------------------------
# QQ Bot message type codes
# ---------------------------------------------------------------------------

MSG_TYPE_TEXT = 0
MSG_TYPE_MARKDOWN = 2
MSG_TYPE_MEDIA = 7
MSG_TYPE_INPUT_NOTIFY = 6

# ---------------------------------------------------------------------------
# QQ Bot file media type codes
# ---------------------------------------------------------------------------

MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_VOICE = 3
MEDIA_TYPE_FILE = 4

# ---------------------------------------------------------------------------
# Runtime SDK configuration
# ---------------------------------------------------------------------------

@dataclass
class SDKConfig:
    """Mutable SDK-wide configuration.

    Do not instantiate directly — use the module-level singleton
    :data:`sdk_config` and the :func:`configure` helper.

    :param source: Identifies the host application in QR-code URLs
        (``?source=<value>``).  Set to empty string to omit the parameter.
        Defaults to empty string (no source parameter).
    :param extra_ua_items: Optional list of extra items to embed in the
        User-Agent header inside the parentheses, separated by semicolons.
        Example: ``["MyApp/1.0.0", "Production"]`` produces::

            QQBotAdapter/1.2.1 (Python/3.11; darwin; MyApp/1.0.0; Production)
    """

    source: str = ""
    extra_ua_items: list[str] = field(default_factory=list)

    def qr_url_template(self) -> str:
        """Return the QR-code URL template with the current *source* baked in.

        The returned string still contains ``{task_id}`` as a placeholder.
        If *source* is empty, the ``?source=`` parameter is omitted entirely.
        """
        base = "https://q.qq.com/qqbot/openclaw/connect.html?task_id={task_id}&_wv=2"
        if self.source:
            return f"{base}&source={self.source}"
        return base


#: Module-level singleton — mutated by :func:`configure`.
sdk_config = SDKConfig()


def configure(
    *,
    source: str | None = None,
    extra_ua_items: list[str] | None = None,
) -> None:
    """Configure SDK-wide runtime settings.

    Call once at application startup, before creating any SDK objects.
    All parameters are keyword-only and optional — omit a parameter to
    leave its current value unchanged.

    :param source: Application identifier embedded in QR-code URLs as
        ``?source=<value>``.  Useful when multiple projects share the
        same QQ Bot credentials and you want to track scan origins.
        Set to empty string to omit the ``source`` parameter entirely.
        Defaults to empty string (no source parameter in QR URLs).
    :param extra_ua_items: Extra items embedded inside the User-Agent
        parentheses, separated by semicolons.  Useful for identifying the
        host framework and environment in server logs.  Example::

            configure(extra_ua_items=["MyApp/1.0.0", "Production"])
            # → QQBotAdapter/1.2.1 (Python/3.11; darwin; MyApp/1.0.0; Production)

    Example::

        from qqbot_agent_sdk import configure
        configure(source="my-app", extra_ua_items=["MyApp/1.0.0"])
    """
    if source is not None:
        sdk_config.source = source
    if extra_ua_items is not None:
        sdk_config.extra_ua_items = extra_ua_items

