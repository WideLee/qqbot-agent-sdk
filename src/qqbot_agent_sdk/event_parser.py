# -*- coding: utf-8 -*-
"""QQ Bot inbound event parser — produces platform-agnostic InboundEvent.

Provides a single, testable :class:`EventParser` that converts raw QQ Bot
dispatch payloads into strongly-typed :class:`InboundEvent` objects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional

from .dto import (
    EventType,
    Message,
    MessageAttachment,
    MsgElement,
    parse_message,
)

logger = logging.getLogger(__name__)

_AT_MENTION_RE = re.compile(r"^@\S+\s*")


# ── InboundEvent ──────────────────────────────────────────────────────

@dataclass
class InboundEvent:
    """Platform-agnostic inbound event produced by :class:`EventParser`.

    Can be consumed by any adapter layer to construct framework-specific
    message event objects.
    """

    event_type: str
    """Original QQ event type string, e.g. ``'C2C_MESSAGE_CREATE'``."""

    chat_id: str
    """Conversation identifier (user openid / group openid / channel id)."""

    user_id: str
    """Sender identifier."""

    chat_scope: str
    """Logical scope: ``'c2c'`` | ``'group'`` | ``'guild'`` | ``'dm'``."""

    content: str
    """Cleaned text content (@ mentions stripped where applicable)."""

    message_id: str
    timestamp: str
    message_type: int

    attachments: List[MessageAttachment] = field(default_factory=list)
    msg_elements: List[MsgElement] = field(default_factory=list)
    user_name: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


# ── EventParser ───────────────────────────────────────────────────────

class EventParser:
    """Parse a raw QQ Bot dispatch payload into an :class:`InboundEvent`.

    Usage::

        parser = EventParser()
        event = parser.parse(event_type, raw_dict)
        if event is None:
            return  # unknown / unsupported event type
    """

    @staticmethod
    def parse(
        event_type: str,
        raw: Dict[str, Any],
    ) -> Optional[InboundEvent]:
        """Parse a raw dispatch payload.

        :param event_type: QQ dispatch event type string.
        :param raw: Raw event dict from the WebSocket frame's ``d`` field.
        :returns: :class:`InboundEvent` or ``None`` if the event type is
            unsupported or required fields are missing.
        """
        if not isinstance(raw, dict):
            return None

        msg = parse_message(raw)
        content = msg.content.strip()

        handler = EventParser._EVENT_HANDLERS.get(event_type)
        if handler is None:
            logger.debug("[EventParser] Unsupported event type: %s", event_type)
            return None

        return handler(event_type, msg, content, raw)

    # ------------------------------------------------------------------
    # Per-event-type handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_c2c(
        event_type: str,
        msg: Message,
        content: str,
        raw: Dict[str, Any],
    ) -> Optional[InboundEvent]:
        user_openid = msg.author.user_openid
        if not user_openid:
            return None
        return InboundEvent(
            event_type=event_type,
            chat_id=user_openid,
            user_id=user_openid,
            chat_scope="c2c",
            content=content,
            message_id=msg.id,
            timestamp=msg.timestamp,
            message_type=msg.message_type,
            attachments=msg.attachments,
            msg_elements=msg.msg_elements,
            raw=raw,
        )

    @staticmethod
    def _parse_group(
        event_type: str,
        msg: Message,
        content: str,
        raw: Dict[str, Any],
    ) -> Optional[InboundEvent]:
        if not msg.group_openid:
            return None
        return InboundEvent(
            event_type=event_type,
            chat_id=msg.group_openid,
            user_id=msg.author.member_openid,
            chat_scope="group",
            content=_strip_at_mention(content),
            message_id=msg.id,
            timestamp=msg.timestamp,
            message_type=msg.message_type,
            attachments=msg.attachments,
            msg_elements=msg.msg_elements,
            raw=raw,
        )

    @staticmethod
    def _parse_guild(
        event_type: str,
        msg: Message,
        content: str,
        raw: Dict[str, Any],
    ) -> Optional[InboundEvent]:
        if not msg.channel_id:
            return None
        nick = (msg.member.nick if msg.member else "") or msg.author.username
        return InboundEvent(
            event_type=event_type,
            chat_id=msg.channel_id,
            user_id=msg.author.id,
            chat_scope="guild",
            content=content,
            message_id=msg.id,
            timestamp=msg.timestamp,
            message_type=msg.message_type,
            attachments=msg.attachments,
            msg_elements=msg.msg_elements,
            user_name=nick or None,
            raw=raw,
        )

    @staticmethod
    def _parse_dm(
        event_type: str,
        msg: Message,
        content: str,
        raw: Dict[str, Any],
    ) -> Optional[InboundEvent]:
        if not msg.guild_id:
            return None
        return InboundEvent(
            event_type=event_type,
            chat_id=msg.guild_id,
            user_id=msg.author.id,
            chat_scope="dm",
            content=content,
            message_id=msg.id,
            timestamp=msg.timestamp,
            message_type=msg.message_type,
            attachments=msg.attachments,
            msg_elements=msg.msg_elements,
            raw=raw,
        )

    # Map event type strings to handler methods.
    # Keys are plain str (EventType is a str-enum, so its members are str instances).
    # This lets callers look up by str without type errors.
    _EVENT_HANDLERS: ClassVar[Dict[str, Any]] = {
        EventType.C2C_MESSAGE_CREATE: _parse_c2c.__func__,  # type: ignore[attr-defined]
        EventType.GROUP_AT_MESSAGE_CREATE: _parse_group.__func__,  # type: ignore[attr-defined]
        EventType.GUILD_MESSAGE_CREATE: _parse_guild.__func__,  # type: ignore[attr-defined]
        EventType.GUILD_AT_MESSAGE_CREATE: _parse_guild.__func__,  # type: ignore[attr-defined]
        EventType.DIRECT_MESSAGE_CREATE: _parse_dm.__func__,  # type: ignore[attr-defined]
    }


# ── Helpers ───────────────────────────────────────────────────────────

def _strip_at_mention(content: str) -> str:
    """Strip the leading @bot mention from group message content."""
    return _AT_MENTION_RE.sub("", content.strip())
