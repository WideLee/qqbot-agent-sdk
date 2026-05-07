# -*- coding: utf-8 -*-
"""qqbot-agent-sdk — Standalone QQ Bot (官方机器人) protocol SDK.

A pure-Python, framework-agnostic implementation of the QQ Bot WebSocket
Gateway and OpenAPI v2.  Can be integrated into any Python project without
pulling in agent-framework dependencies.

Dependencies: ``aiohttp`` (WebSocket), ``httpx`` (HTTP), ``cryptography``
(onboard AES-GCM).  Optional: ``pilk`` (silk audio), ``qrcode`` (terminal
QR rendering), ``ffmpeg`` (audio conversion via subprocess).

Quick start
-----------
::

    from qqbot_agent_sdk import QQApiClient, QQWebSocket, WSCallbacks, EventParser

Public surface
--------------
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("qqbot-agent-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

# ── Core API client ───────────────────────────────────────────────────
from .api_client import QQApiClient  # noqa: F401

# ── WebSocket gateway ─────────────────────────────────────────────────
from .websocket import QQCloseError, QQWebSocket, WSCallbacks  # noqa: F401

# ── Inbound event parsing ─────────────────────────────────────────────
from .event_parser import EventParser, InboundEvent  # noqa: F401

# ── Attachment & media handling ───────────────────────────────────────
from .attachment import (  # noqa: F401
    AttachmentDownloader,
    AttachmentProcessor,
    ProcessedAttachment,
    describe_attachment,
)
from .media_loader import (  # noqa: F401
    MediaLoadResult,
    MediaLoader,
    MediaUploader,
    UploadDailyLimitExceededError,
    UploadFileTooLargeError,
)

# ── Approval / inline keyboard helpers ───────────────────────────────
from .approval import (  # noqa: F401
    ApprovalRequest,
    ApprovalSender,
    build_approval_keyboard,
    build_approval_text,
    build_update_prompt_keyboard,
    parse_approval_button_data,
    parse_update_prompt_button_data,
)

# ── QR-code onboard flow ──────────────────────────────────────────────
from .onboard import (  # noqa: F401
    BindStatus,
    OnboardAPIError,
    OnboardError,
    OnboardExpiredError,
    OnboardResult,
    build_connect_url,
    start_onboard,
)

# ── Data transfer objects (commonly needed by adapters) ───────────────
from .dto import (  # noqa: F401
    DEFAULT_INTENTS,
    EventType,
    GuildMessageToCreate,
    InputNotify,
    Intent,
    InlineKeyboard,
    InteractionEvent,
    MediaInfo,
    MessageAttachment,
    MessageToCreate,
    MSG_TYPE_QUOTE,
    OPCode,
    QQMessageType,
    parse_interaction_event,
)

# ── Audio utilities ───────────────────────────────────────────────────
from .audio import (  # noqa: F401
    STTConfig,
    STTPipeline,
    is_voice_content_type,
    resolve_stt_config,
)

# ── Session persistence ───────────────────────────────────────────────
from .session_store import WSSessionStore  # noqa: F401

# ── Constants ─────────────────────────────────────────────────────────
from .constants import (  # noqa: F401
    MAX_MESSAGE_LENGTH,
    MEDIA_TYPE_FILE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VOICE,
    ONBOARD_POLL_INTERVAL,
    QQBOT_VERSION,
    SDKConfig,
    configure,
    sdk_config,
)

# ── Misc helpers ──────────────────────────────────────────────────────
from .utils import (  # noqa: F401
    append_block,
    build_user_agent,
    coerce_list,
    entry_matches,
    get_api_headers,
    is_fatal_send_error,
    parse_qq_timestamp,
)
