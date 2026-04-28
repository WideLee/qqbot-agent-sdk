# -*- coding: utf-8 -*-
"""Unit tests for qqbot_agent_sdk.dto module.

Covers all enums, dataclasses, serialisation helpers (``to_dict``),
parsing factories, and close-code classification.
"""

import pytest

from qqbot_agent_sdk.dto import (
    CloseAction,
    CompleteUploadRequest,
    CompleteUploadResponse,
    EventType,
    GuildMessageToCreate,
    InlineKeyboard,
    InputNotify,
    Intent,
    InteractionData,
    InteractionEvent,
    InteractionResolved,
    KeyboardButton,
    KeyboardButtonAction,
    KeyboardButtonPermission,
    KeyboardButtonRenderData,
    KeyboardContent,
    KeyboardRow,
    MarkdownContent,
    MediaInfo,
    Member,
    Message,
    MessageAttachment,
    MessageReference,
    MessageScene,
    MessageToCreate,
    MsgElement,
    OPCode,
    QQMessageType,
    RichMediaMessage,
    UploadConfig,
    UploadPart,
    UploadPartFinishRequest,
    UploadPrepareRequest,
    UploadPrepareResponse,
    User,
    WSHelloData,
    WSPayload,
    WSReadyData,
    classify_close_code,
    parse_complete_upload,
    parse_hello,
    parse_interaction_event,
    parse_message,
    parse_ready,
    parse_upload_prepare,
    parse_ws_payload,
    DEFAULT_INTENTS,
    INTERACTION_EVENT_TYPES,
    MESSAGE_EVENT_TYPES,
    MSG_TYPE_QUOTE,
    FileHashInfo,
)


# ======================================================================
# Enums
# ======================================================================

class TestOPCode:
    """OPCode enum values."""

    def test_dispatch(self):
        assert OPCode.DISPATCH == 0

    def test_heartbeat(self):
        assert OPCode.HEARTBEAT == 1

    def test_identify(self):
        assert OPCode.IDENTIFY == 2

    def test_resume(self):
        assert OPCode.RESUME == 6

    def test_reconnect(self):
        assert OPCode.RECONNECT == 7

    def test_invalid_session(self):
        assert OPCode.INVALID_SESSION == 9

    def test_hello(self):
        assert OPCode.HELLO == 10

    def test_heartbeat_ack(self):
        assert OPCode.HEARTBEAT_ACK == 11

    def test_is_int(self):
        assert isinstance(OPCode.DISPATCH, int)


class TestEventType:
    """EventType enum values."""

    def test_ready(self):
        assert EventType.READY == "READY"
        assert EventType.READY.value == "READY"

    def test_c2c_message_create(self):
        assert EventType.C2C_MESSAGE_CREATE == "C2C_MESSAGE_CREATE"

    def test_group_at_message_create(self):
        assert EventType.GROUP_AT_MESSAGE_CREATE == "GROUP_AT_MESSAGE_CREATE"

    def test_interaction_create(self):
        assert EventType.INTERACTION_CREATE == "INTERACTION_CREATE"

    def test_is_str(self):
        assert isinstance(EventType.READY, str)


class TestIntent:
    """Intent IntFlag bitmask."""

    def test_individual_bits(self):
        assert Intent.GUILDS == 1
        assert Intent.GUILD_MEMBERS == 2
        assert Intent.GUILD_MESSAGES == (1 << 9)
        assert Intent.DIRECT_MESSAGES == (1 << 12)
        assert Intent.INTERACTION == (1 << 26)
        assert Intent.GROUP_MESSAGES == (1 << 25)
        assert Intent.GUILD_AT_MESSAGE == (1 << 30)

    def test_combination(self):
        combined = Intent.GUILDS | Intent.GUILD_MEMBERS
        assert combined & Intent.GUILDS
        assert combined & Intent.GUILD_MEMBERS
        assert not (combined & Intent.DIRECT_MESSAGES)

    def test_default_intents(self):
        expected = (
            Intent.GROUP_MESSAGES
            | Intent.GUILD_AT_MESSAGE
            | Intent.DIRECT_MESSAGES
            | Intent.INTERACTION
        )
        assert DEFAULT_INTENTS == expected


class TestQQMessageType:
    """QQMessageType enum values."""

    def test_values(self):
        assert QQMessageType.TEXT == 0
        assert QQMessageType.MARKDOWN == 2
        assert QQMessageType.ARK == 3
        assert QQMessageType.EMBED == 4
        assert QQMessageType.INPUT_NOTIFY == 6
        assert QQMessageType.RICH_MEDIA == 7


class TestCloseAction:
    """CloseAction string enum."""

    def test_values(self):
        assert CloseAction.STOP == "stop"
        assert CloseAction.RESUME_OK == "resume_ok"
        assert CloseAction.IDENTIFY_ONLY == "identify_only"
        assert CloseAction.RATE_LIMIT == "rate_limit"
        assert CloseAction.RECONNECT == "reconnect"


# ======================================================================
# Module-level constants
# ======================================================================

class TestConstants:
    """Module constants: event type sets, MSG_TYPE_QUOTE."""

    def test_message_event_types(self):
        assert EventType.C2C_MESSAGE_CREATE in MESSAGE_EVENT_TYPES
        assert EventType.GROUP_AT_MESSAGE_CREATE in MESSAGE_EVENT_TYPES
        assert EventType.DIRECT_MESSAGE_CREATE in MESSAGE_EVENT_TYPES
        assert EventType.GUILD_MESSAGE_CREATE in MESSAGE_EVENT_TYPES
        assert EventType.GUILD_AT_MESSAGE_CREATE in MESSAGE_EVENT_TYPES
        assert len(MESSAGE_EVENT_TYPES) == 5

    def test_interaction_event_types(self):
        assert EventType.INTERACTION_CREATE in INTERACTION_EVENT_TYPES
        assert len(INTERACTION_EVENT_TYPES) == 1

    def test_msg_type_quote(self):
        assert MSG_TYPE_QUOTE == 103


# ======================================================================
# Inbound DTOs — defaults and construction
# ======================================================================

class TestUser:
    """User dataclass."""

    def test_defaults(self):
        user = User()
        assert user.id == ""
        assert user.username == ""
        assert user.avatar == ""
        assert user.bot is False
        assert user.union_openid == ""
        assert user.user_openid == ""
        assert user.member_openid == ""

    def test_custom(self):
        user = User(
            id="u1",
            username="alice",
            avatar="https://img.qq.com/a.png",
            bot=True,
            user_openid="open123",
        )
        assert user.id == "u1"
        assert user.username == "alice"
        assert user.bot is True
        assert user.user_openid == "open123"


class TestMember:
    """Member dataclass."""

    def test_defaults(self):
        m = Member()
        assert m.guild_id == ""
        assert m.nick == ""
        assert m.user is None
        assert m.roles == []
        assert m.joined_at == ""

    def test_with_user(self):
        m = Member(guild_id="g1", user=User(id="u1"), roles=["admin"])
        assert m.guild_id == "g1"
        assert m.user.id == "u1"
        assert "admin" in m.roles


class TestMessageAttachment:
    """MessageAttachment dataclass and resolved_url property."""

    def test_defaults(self):
        att = MessageAttachment()
        assert att.url == ""
        assert att.filename == ""
        assert att.content_type == ""
        assert att.height == 0
        assert att.width == 0
        assert att.size == 0
        assert att.voice_wav_url == ""
        assert att.asr_refer_text == ""

    def test_resolved_url_with_double_slash(self):
        att = MessageAttachment(url="//multimedia.nt.qq.com/abc.png")
        assert att.resolved_url == "https://multimedia.nt.qq.com/abc.png"

    def test_resolved_url_with_full_url(self):
        att = MessageAttachment(url="https://example.com/img.jpg")
        assert att.resolved_url == "https://example.com/img.jpg"

    def test_resolved_url_empty(self):
        att = MessageAttachment(url="")
        assert att.resolved_url == ""

    def test_resolved_url_trims_whitespace(self):
        att = MessageAttachment(url="  //example.com/x  ")
        assert att.resolved_url == "https://example.com/x"

    def test_voice_fields(self):
        att = MessageAttachment(
            url="//voice.qq.com/a.amr",
            voice_wav_url="https://wav.qq.com/a.wav",
            asr_refer_text="你好",
        )
        assert att.voice_wav_url == "https://wav.qq.com/a.wav"
        assert att.asr_refer_text == "你好"


class TestMsgElement:
    """MsgElement dataclass."""

    def test_defaults(self):
        elem = MsgElement()
        assert elem.msg_idx == ""
        assert elem.content == ""
        assert elem.attachments == []

    def test_with_attachments(self):
        att = MessageAttachment(url="//img.qq.com/x.png")
        elem = MsgElement(msg_idx="0", content="hello", attachments=[att])
        assert len(elem.attachments) == 1
        assert elem.attachments[0].url == "//img.qq.com/x.png"


class TestMessageScene:
    """MessageScene dataclass."""

    def test_defaults(self):
        scene = MessageScene()
        assert scene.ext == []

    def test_with_ext(self):
        scene = MessageScene(ext=["voice", "image"])
        assert scene.ext == ["voice", "image"]


class TestMessage:
    """Message dataclass."""

    def test_defaults(self):
        msg = Message()
        assert msg.id == ""
        assert msg.content == ""
        assert msg.message_type == 0
        assert msg.attachments == []
        assert msg.msg_elements == []
        assert msg.message_scene is None
        assert msg.direct_message is False
        assert isinstance(msg.author, User)

    def test_custom(self):
        msg = Message(
            id="msg1",
            group_openid="g123",
            content="hello",
            message_type=MSG_TYPE_QUOTE,
            direct_message=True,
        )
        assert msg.id == "msg1"
        assert msg.group_openid == "g123"
        assert msg.content == "hello"
        assert msg.message_type == MSG_TYPE_QUOTE
        assert msg.direct_message is True


# ======================================================================
# WebSocket Payload DTOs
# ======================================================================

class TestWSPayload:
    """WSPayload dataclass."""

    def test_defaults(self):
        p = WSPayload()
        assert p.op == 0
        assert p.s is None
        assert p.t == ""
        assert p.d is None

    def test_custom(self):
        p = WSPayload(op=10, s=1, t="READY", d={"session_id": "abc"})
        assert p.op == 10
        assert p.s == 1
        assert p.t == "READY"
        assert p.d == {"session_id": "abc"}


class TestWSHelloData:
    """WSHelloData dataclass."""

    def test_default_heartbeat_interval(self):
        h = WSHelloData()
        assert h.heartbeat_interval == 30000

    def test_custom(self):
        h = WSHelloData(heartbeat_interval=45000)
        assert h.heartbeat_interval == 45000


class TestWSReadyData:
    """WSReadyData dataclass."""

    def test_defaults(self):
        r = WSReadyData()
        assert r.version == 0
        assert r.session_id == ""
        assert r.user is None
        assert r.shard == []


# ======================================================================
# classify_close_code
# ======================================================================

class TestClassifyCloseCode:
    """classify_close_code function."""

    def test_none_returns_reconnect(self):
        assert classify_close_code(None) == CloseAction.RECONNECT

    @pytest.mark.parametrize("code", [4001, 4002, 4010, 4011, 4012, 4013, 4014, 4914, 4915])
    def test_fatal_codes(self, code):
        assert classify_close_code(code) == CloseAction.STOP

    def test_rate_limit_4008(self):
        assert classify_close_code(4008) == CloseAction.RATE_LIMIT

    def test_resume_ok_4009(self):
        assert classify_close_code(4009) == CloseAction.RESUME_OK

    @pytest.mark.parametrize("code", [4006, 4007])
    def test_identify_only_base(self, code):
        assert classify_close_code(code) == CloseAction.IDENTIFY_ONLY

    @pytest.mark.parametrize("code", range(4900, 4914))
    def test_identify_only_internal_errors(self, code):
        assert classify_close_code(code) == CloseAction.IDENTIFY_ONLY

    def test_unknown_code(self):
        assert classify_close_code(9999) == CloseAction.RECONNECT

    def test_normal_close_1000(self):
        assert classify_close_code(1000) == CloseAction.RECONNECT


# ======================================================================
# Outbound DTOs — to_dict serialisation
# ======================================================================

class TestMessageToCreate:
    """MessageToCreate dataclass and to_dict."""

    def test_minimal_text(self):
        m = MessageToCreate(content="hi", msg_type=0, msg_id="m1")
        d = m.to_dict()
        assert d == {"msg_type": 0, "msg_id": "m1", "content": "hi"}

    def test_with_msg_seq(self):
        m = MessageToCreate(msg_type=0, msg_seq=42)
        d = m.to_dict()
        assert d["msg_seq"] == 42

    def test_with_markdown(self):
        m = MessageToCreate(
            msg_type=2,
            markdown=MarkdownContent(content="**bold**"),
        )
        d = m.to_dict()
        assert d["markdown"] == {"content": "**bold**"}

    def test_with_media(self):
        m = MessageToCreate(
            msg_type=7,
            media=MediaInfo(file_info="abc123"),
        )
        d = m.to_dict()
        assert d["media"] == {"file_info": "abc123"}

    def test_with_message_reference(self):
        m = MessageToCreate(
            msg_type=0,
            content="reply",
            message_reference=MessageReference(message_id="ref1"),
        )
        d = m.to_dict()
        assert d["message_reference"] == {"message_id": "ref1"}

    def test_with_input_notify(self):
        m = MessageToCreate(
            msg_type=6,
            input_notify=InputNotify(input_type=1, input_second=30),
        )
        d = m.to_dict()
        assert d["input_notify"] == {"input_type": 1, "input_second": 30}

    def test_empty_fields_omitted(self):
        m = MessageToCreate(msg_type=0)
        d = m.to_dict()
        assert "content" not in d
        assert "markdown" not in d
        assert "media" not in d
        assert "msg_seq" not in d
        assert "msg_id" not in d


class TestRichMediaMessage:
    """RichMediaMessage dataclass and to_dict."""

    def test_minimal(self):
        rm = RichMediaMessage(file_type=1, url="https://img.qq.com/a.png")
        d = rm.to_dict()
        assert d == {
            "file_type": 1,
            "srv_send_msg": False,
            "url": "https://img.qq.com/a.png",
        }

    def test_with_file_data(self):
        rm = RichMediaMessage(file_type=3, file_data="base64data", file_name="audio.amr")
        d = rm.to_dict()
        assert d["file_data"] == "base64data"
        assert d["file_name"] == "audio.amr"
        assert "url" not in d

    def test_empty_optional_omitted(self):
        rm = RichMediaMessage(file_type=1)
        d = rm.to_dict()
        assert "url" not in d
        assert "file_data" not in d
        assert "file_name" not in d


class TestGuildMessageToCreate:
    """GuildMessageToCreate dataclass and to_dict."""

    def test_basic(self):
        g = GuildMessageToCreate(content="hello guild", msg_id="gm1")
        d = g.to_dict()
        assert d == {"content": "hello guild", "msg_id": "gm1"}

    def test_no_msg_id(self):
        g = GuildMessageToCreate(content="hello")
        d = g.to_dict()
        assert d == {"content": "hello"}
        assert "msg_id" not in d


# ======================================================================
# Chunked upload DTOs
# ======================================================================

class TestFileHashInfo:
    """FileHashInfo dataclass."""

    def test_creation(self):
        fh = FileHashInfo(md5="aaa", sha1="bbb", md5_10m="ccc")
        assert fh.md5 == "aaa"
        assert fh.sha1 == "bbb"
        assert fh.md5_10m == "ccc"


class TestUploadPrepareRequest:
    """UploadPrepareRequest to_dict."""

    def test_to_dict(self):
        req = UploadPrepareRequest(
            file_type=1,
            file_size=1024,
            file_name="photo.png",
            md5="abc",
            sha1="def",
            md5_10m="abc",
        )
        d = req.to_dict()
        assert d == {
            "file_type": 1,
            "file_size": 1024,
            "file_name": "photo.png",
            "md5": "abc",
            "sha1": "def",
            "md5_10m": "abc",
        }


class TestUploadPartFinishRequest:
    """UploadPartFinishRequest to_dict."""

    def test_to_dict(self):
        req = UploadPartFinishRequest(
            upload_id="uid1",
            part_index=1,
            block_size=4096,
            md5="partmd5",
        )
        d = req.to_dict()
        assert d == {
            "upload_id": "uid1",
            "part_index": 1,
            "block_size": 4096,
            "md5": "partmd5",
        }


class TestCompleteUploadRequest:
    """CompleteUploadRequest to_dict."""

    def test_to_dict(self):
        req = CompleteUploadRequest(upload_id="uid1")
        d = req.to_dict()
        assert d == {"upload_id": "uid1"}


class TestUploadConfig:
    """UploadConfig defaults."""

    def test_defaults(self):
        cfg = UploadConfig()
        assert cfg.concurrency == 1
        assert cfg.retry_timeout == 0
        assert cfg.retry_delay == 0

    def test_custom(self):
        cfg = UploadConfig(concurrency=4, retry_timeout=30, retry_delay=5)
        assert cfg.concurrency == 4
        assert cfg.retry_timeout == 30
        assert cfg.retry_delay == 5


class TestUploadPart:
    """UploadPart dataclass."""

    def test_creation(self):
        part = UploadPart(index=1, presigned_url="https://cos.qq.com/upload/1")
        assert part.index == 1
        assert part.presigned_url == "https://cos.qq.com/upload/1"
        assert part.block_size == 0


class TestUploadPrepareResponse:
    """UploadPrepareResponse dataclass and __post_init__."""

    def test_auto_creates_upload_config(self):
        resp = UploadPrepareResponse(
            upload_id="uid1",
            block_size=4096,
            parts=[UploadPart(index=1, presigned_url="https://cos/1")],
        )
        assert isinstance(resp.upload_config, UploadConfig)
        assert resp.upload_config.concurrency == 1

    def test_concurrency_property(self):
        resp = UploadPrepareResponse(
            upload_id="uid1",
            block_size=4096,
            parts=[UploadPart(index=1, presigned_url="https://cos/1")],
            upload_config=UploadConfig(concurrency=8),
        )
        assert resp.concurrency == 8

    def test_retry_timeout_property(self):
        resp = UploadPrepareResponse(
            upload_id="uid1",
            block_size=4096,
            parts=[],
            upload_config=UploadConfig(retry_timeout=60),
        )
        assert resp.retry_timeout == 60.0
        assert isinstance(resp.retry_timeout, float)


class TestCompleteUploadResponse:
    """CompleteUploadResponse and token property."""

    def test_defaults(self):
        resp = CompleteUploadResponse()
        assert resp.file_info == ""
        assert resp.file_uuid == ""
        assert resp.ttl == 0

    def test_token_prefers_file_info(self):
        resp = CompleteUploadResponse(file_info="info1", file_uuid="uuid1")
        assert resp.token == "info1"

    def test_token_fallback_to_file_uuid(self):
        resp = CompleteUploadResponse(file_info="", file_uuid="uuid1")
        assert resp.token == "uuid1"

    def test_token_empty_when_both_empty(self):
        resp = CompleteUploadResponse()
        assert resp.token == ""


# ======================================================================
# Keyboard DTOs — to_dict serialisation
# ======================================================================

class TestKeyboardButtonPermission:
    """KeyboardButtonPermission defaults."""

    def test_default_type(self):
        perm = KeyboardButtonPermission()
        assert perm.type == 2


class TestKeyboardButtonAction:
    """KeyboardButtonAction and __post_init__."""

    def test_default_permission(self):
        action = KeyboardButtonAction(type=1, data="approve:123:yes")
        assert isinstance(action.permission, KeyboardButtonPermission)
        assert action.permission.type == 2
        assert action.click_limit == 1

    def test_to_dict(self):
        action = KeyboardButtonAction(type=1, data="payload")
        d = action.to_dict()
        assert d == {
            "type": 1,
            "data": "payload",
            "permission": {"type": 2},
            "click_limit": 1,
        }


class TestKeyboardButtonRenderData:
    """KeyboardButtonRenderData to_dict."""

    def test_to_dict(self):
        rd = KeyboardButtonRenderData(label="Approve", visited_label="Approved", style=1)
        d = rd.to_dict()
        assert d == {"label": "Approve", "visited_label": "Approved", "style": 1}

    def test_default_style(self):
        rd = KeyboardButtonRenderData(label="X", visited_label="Y")
        assert rd.style == 1


class TestKeyboardButton:
    """KeyboardButton to_dict."""

    def test_to_dict(self):
        btn = KeyboardButton(
            id="btn1",
            render_data=KeyboardButtonRenderData(label="OK", visited_label="Done"),
            action=KeyboardButtonAction(type=1, data="ok"),
        )
        d = btn.to_dict()
        assert d["id"] == "btn1"
        assert d["render_data"]["label"] == "OK"
        assert d["action"]["type"] == 1
        assert d["group_id"] == "default"

    def test_custom_group_id(self):
        btn = KeyboardButton(
            id="btn2",
            render_data=KeyboardButtonRenderData(label="A", visited_label="B"),
            action=KeyboardButtonAction(type=1, data="a"),
            group_id="grp1",
        )
        assert btn.to_dict()["group_id"] == "grp1"


class TestKeyboardRow:
    """KeyboardRow to_dict."""

    def test_empty(self):
        row = KeyboardRow()
        assert row.to_dict() == {"buttons": []}

    def test_with_buttons(self):
        btn = KeyboardButton(
            id="b1",
            render_data=KeyboardButtonRenderData(label="L", visited_label="V"),
            action=KeyboardButtonAction(type=1, data="d"),
        )
        row = KeyboardRow(buttons=[btn])
        d = row.to_dict()
        assert len(d["buttons"]) == 1
        assert d["buttons"][0]["id"] == "b1"


class TestKeyboardContent:
    """KeyboardContent to_dict."""

    def test_empty(self):
        kc = KeyboardContent()
        assert kc.to_dict() == {"rows": []}

    def test_with_rows(self):
        row = KeyboardRow(buttons=[])
        kc = KeyboardContent(rows=[row])
        assert len(kc.to_dict()["rows"]) == 1


class TestInlineKeyboard:
    """InlineKeyboard to_dict."""

    def test_default(self):
        kb = InlineKeyboard()
        assert kb.to_dict() == {"content": {"rows": []}}


# ======================================================================
# InteractionEvent DTO and properties
# ======================================================================

class TestInteractionResolved:
    """InteractionResolved defaults."""

    def test_defaults(self):
        r = InteractionResolved()
        assert r.button_data == ""
        assert r.button_id == ""
        assert r.user_id == ""


class TestInteractionData:
    """InteractionData defaults."""

    def test_defaults(self):
        d = InteractionData()
        assert d.type == 0
        assert isinstance(d.resolved, InteractionResolved)


class TestInteractionEvent:
    """InteractionEvent properties."""

    def test_defaults(self):
        ie = InteractionEvent()
        assert ie.id == ""
        assert ie.type == 0
        assert ie.operator_openid == ""
        assert ie.chat_id == ""
        assert ie.is_c2c is False
        assert ie.is_group is False

    def test_group_scene(self):
        ie = InteractionEvent(
            group_openid="g123",
            group_member_openid="m456",
        )
        assert ie.is_group is True
        assert ie.is_c2c is False
        assert ie.operator_openid == "m456"
        assert ie.chat_id == "g123"

    def test_c2c_scene(self):
        ie = InteractionEvent(user_openid="u789")
        assert ie.is_c2c is True
        assert ie.is_group is False
        assert ie.operator_openid == "u789"
        assert ie.chat_id == "u789"

    def test_operator_openid_fallback_to_resolved(self):
        ie = InteractionEvent(
            data=InteractionData(
                resolved=InteractionResolved(user_id="resolved_uid"),
            ),
        )
        assert ie.operator_openid == "resolved_uid"

    def test_chat_id_guild_channel(self):
        ie = InteractionEvent(channel_id="ch1")
        assert ie.chat_id == "ch1"

    def test_chat_id_priority(self):
        """group_openid > user_openid > channel_id."""
        ie = InteractionEvent(
            group_openid="g1",
            user_openid="u1",
            channel_id="ch1",
        )
        assert ie.chat_id == "g1"


# ======================================================================
# Parsing factories
# ======================================================================

class TestParseMessage:
    """parse_message function."""

    def test_minimal(self):
        msg = parse_message({})
        assert msg.id == ""
        assert msg.content == ""
        assert msg.attachments == []
        assert msg.msg_elements == []
        assert isinstance(msg.author, User)
        assert msg.member is None

    def test_full_message(self):
        raw = {
            "id": "msg1",
            "channel_id": "ch1",
            "guild_id": "gd1",
            "group_id": "grp1",
            "group_openid": "go1",
            "content": "hello world",
            "timestamp": "2026-01-01T00:00:00Z",
            "author": {
                "id": "uid1",
                "username": "alice",
                "user_openid": "uo1",
            },
            "member": {
                "guild_id": "gd1",
                "nick": "Alice",
                "roles": ["admin"],
            },
            "attachments": [
                {"url": "//img.qq.com/1.png", "filename": "1.png", "content_type": "image/png"},
            ],
            "direct_message": True,
            "src_guild_id": "sgd1",
            "message_type": 0,
        }
        msg = parse_message(raw)
        assert msg.id == "msg1"
        assert msg.content == "hello world"
        assert msg.author.id == "uid1"
        assert msg.author.user_openid == "uo1"
        assert msg.member is not None
        assert msg.member.nick == "Alice"
        assert len(msg.attachments) == 1
        assert msg.attachments[0].url == "//img.qq.com/1.png"
        assert msg.direct_message is True

    def test_with_attachments_none_filtered(self):
        """Non-dict attachment entries are skipped."""
        raw = {
            "attachments": [
                {"url": "//img.qq.com/1.png"},
                "invalid",
                None,
            ],
        }
        msg = parse_message(raw)
        assert len(msg.attachments) == 1

    def test_voice_attachment(self):
        raw = {
            "attachments": [
                {
                    "url": "//voice.qq.com/a.amr",
                    "content_type": "audio/amr",
                    "voice_wav_url": "https://wav.qq.com/a.wav",
                    "asr_refer_text": "你好",
                },
            ],
        }
        msg = parse_message(raw)
        att = msg.attachments[0]
        assert att.voice_wav_url == "https://wav.qq.com/a.wav"
        assert att.asr_refer_text == "你好"

    def test_message_scene(self):
        raw = {
            "message_scene": {
                "ext": ["voice", "image"],
            },
        }
        msg = parse_message(raw)
        assert msg.message_scene is not None
        assert msg.message_scene.ext == ["voice", "image"]

    def test_message_scene_invalid_ext(self):
        """Non-string entries in ext are filtered."""
        raw = {
            "message_scene": {
                "ext": ["voice", 123, None],
            },
        }
        msg = parse_message(raw)
        assert msg.message_scene.ext == ["voice"]

    def test_message_scene_non_dict(self):
        raw = {"message_scene": "invalid"}
        msg = parse_message(raw)
        assert msg.message_scene is None

    def test_msg_elements_with_quote(self):
        raw = {
            "message_type": MSG_TYPE_QUOTE,
            "msg_elements": [
                {
                    "msg_idx": "0",
                    "content": "original text",
                    "attachments": [
                        {"url": "//img.qq.com/quoted.png"},
                    ],
                },
            ],
        }
        msg = parse_message(raw)
        assert msg.message_type == MSG_TYPE_QUOTE
        assert len(msg.msg_elements) == 1
        elem = msg.msg_elements[0]
        assert elem.content == "original text"
        assert len(elem.attachments) == 1

    def test_msg_elements_skips_non_dict(self):
        raw = {
            "msg_elements": [
                {"msg_idx": "0", "content": "ok"},
                "invalid",
                None,
            ],
        }
        msg = parse_message(raw)
        assert len(msg.msg_elements) == 1

    def test_null_height_width_size(self):
        """height/width/size=None should be treated as 0."""
        raw = {
            "attachments": [
                {"url": "//img.qq.com/1.png", "height": None, "width": None, "size": None},
            ],
        }
        msg = parse_message(raw)
        att = msg.attachments[0]
        assert att.height == 0
        assert att.width == 0
        assert att.size == 0

    def test_author_non_dict(self):
        """Non-dict author falls back to default User."""
        raw = {"author": "invalid"}
        msg = parse_message(raw)
        assert msg.author.id == ""

    def test_member_non_dict(self):
        """Non-dict member falls back to None."""
        raw = {"member": "invalid"}
        msg = parse_message(raw)
        assert msg.member is None


class TestParseWSPayload:
    """parse_ws_payload function."""

    def test_basic(self):
        raw = {"op": 0, "s": 42, "t": "C2C_MESSAGE_CREATE", "d": {"id": "m1"}}
        p = parse_ws_payload(raw)
        assert p.op == 0
        assert p.s == 42
        assert p.t == "C2C_MESSAGE_CREATE"
        assert p.d == {"id": "m1"}

    def test_hello(self):
        raw = {"op": 10, "d": {"heartbeat_interval": 45000}}
        p = parse_ws_payload(raw)
        assert p.op == 10
        assert p.s is None
        assert p.t == ""

    def test_empty_t(self):
        raw = {"op": 11, "t": ""}
        p = parse_ws_payload(raw)
        assert p.t == ""

    def test_none_t(self):
        raw = {"op": 11, "t": None}
        p = parse_ws_payload(raw)
        assert p.t == ""

    def test_enum_value_t(self):
        """If t is an enum-like object with .value, it extracts the value."""
        raw = {"op": 0, "t": EventType.READY}
        p = parse_ws_payload(raw)
        assert p.t == "READY"

    def test_defaults(self):
        p = parse_ws_payload({})
        assert p.op == 0
        assert p.s is None
        assert p.t == ""
        assert p.d is None


class TestParseHello:
    """parse_hello function."""

    def test_normal(self):
        h = parse_hello({"heartbeat_interval": 45000})
        assert h.heartbeat_interval == 45000

    def test_default(self):
        h = parse_hello({})
        assert h.heartbeat_interval == 30000

    def test_non_dict(self):
        h = parse_hello("invalid")
        assert h.heartbeat_interval == 30000

    def test_none(self):
        h = parse_hello(None)
        assert h.heartbeat_interval == 30000


class TestParseReady:
    """parse_ready function."""

    def test_normal(self):
        raw = {
            "version": 1,
            "session_id": "sess1",
            "user": {"id": "bot1", "username": "MyBot"},
            "shard": [0, 1],
        }
        r = parse_ready(raw)
        assert r.version == 1
        assert r.session_id == "sess1"
        assert r.user.id == "bot1"
        assert r.shard == [0, 1]

    def test_non_dict(self):
        r = parse_ready(None)
        assert r.version == 0
        assert r.session_id == ""
        assert r.user is None
        assert r.shard == []

    def test_empty_dict(self):
        r = parse_ready({})
        assert r.version == 0
        assert r.session_id == ""


class TestParseUploadPrepare:
    """parse_upload_prepare function."""

    def test_normal(self):
        raw = {
            "upload_id": "uid1",
            "block_size": 4096,
            "parts": [
                {"index": 1, "presigned_url": "https://cos/1", "block_size": 0},
                {"index": 2, "presigned_url": "https://cos/2", "block_size": 0},
            ],
            "upload_config": {
                "concurrency": 4,
                "retry_timeout": 30,
                "retry_delay": 5,
            },
        }
        resp = parse_upload_prepare(raw)
        assert resp.upload_id == "uid1"
        assert resp.block_size == 4096
        assert len(resp.parts) == 2
        assert resp.parts[0].presigned_url == "https://cos/1"
        assert resp.concurrency == 4
        assert resp.upload_config.retry_timeout == 30

    def test_missing_upload_id_raises(self):
        with pytest.raises(ValueError, match="missing upload_id"):
            parse_upload_prepare({"block_size": 4096, "parts": [{"index": 1, "presigned_url": "x"}]})

    def test_missing_block_size_raises(self):
        with pytest.raises(ValueError, match="missing block_size"):
            parse_upload_prepare({"upload_id": "uid1", "parts": [{"index": 1, "presigned_url": "x"}]})

    def test_no_parts_raises(self):
        with pytest.raises(ValueError, match="no parts"):
            parse_upload_prepare({"upload_id": "uid1", "block_size": 4096, "parts": []})

    def test_non_dict_parts_skipped(self):
        with pytest.raises(ValueError, match="no parts"):
            parse_upload_prepare({
                "upload_id": "uid1",
                "block_size": 4096,
                "parts": ["invalid", None],
            })

    def test_fallback_config_from_root(self):
        """When upload_config is not a dict, config is read from root."""
        raw = {
            "upload_id": "uid1",
            "block_size": 4096,
            "parts": [{"index": 1, "presigned_url": "https://cos/1"}],
            "concurrency": 8,
            "retry_timeout": 60,
        }
        resp = parse_upload_prepare(raw)
        assert resp.concurrency == 8
        assert resp.upload_config.retry_timeout == 60

    def test_default_config(self):
        """Without any config fields, defaults are used."""
        raw = {
            "upload_id": "uid1",
            "block_size": 4096,
            "parts": [{"index": 1, "presigned_url": "https://cos/1"}],
        }
        resp = parse_upload_prepare(raw)
        assert resp.concurrency == 1
        assert resp.upload_config.retry_timeout == 0


class TestParseCompleteUpload:
    """parse_complete_upload function."""

    def test_normal(self):
        raw = {"file_info": "fi1", "file_uuid": "fu1", "ttl": 86400}
        resp = parse_complete_upload(raw)
        assert resp.file_info == "fi1"
        assert resp.file_uuid == "fu1"
        assert resp.ttl == 86400
        assert resp.token == "fi1"

    def test_empty(self):
        resp = parse_complete_upload({})
        assert resp.file_info == ""
        assert resp.file_uuid == ""
        assert resp.ttl == 0
        assert resp.token == ""

    def test_null_ttl(self):
        resp = parse_complete_upload({"ttl": None})
        assert resp.ttl == 0


class TestParseInteractionEvent:
    """parse_interaction_event function."""

    def test_group_button_click(self):
        raw = {
            "id": "evt1",
            "type": 11,
            "chat_type": 1,
            "scene": "group",
            "group_openid": "g123",
            "group_member_openid": "m456",
            "data": {
                "type": 11,
                "resolved": {
                    "button_data": "approve:req1:yes",
                    "button_id": "btn_approve",
                },
            },
        }
        ie = parse_interaction_event(raw)
        assert ie.id == "evt1"
        assert ie.type == 11
        assert ie.chat_type == 1
        assert ie.scene == "group"
        assert ie.group_openid == "g123"
        assert ie.group_member_openid == "m456"
        assert ie.data.type == 11
        assert ie.data.resolved.button_data == "approve:req1:yes"
        assert ie.data.resolved.button_id == "btn_approve"
        assert ie.is_group is True
        assert ie.operator_openid == "m456"

    def test_c2c_button_click(self):
        raw = {
            "id": "evt2",
            "type": 11,
            "chat_type": 2,
            "scene": "c2c",
            "user_openid": "u789",
            "data": {
                "type": 11,
                "resolved": {
                    "button_data": "approve:req2:no",
                    "button_id": "btn_reject",
                },
            },
        }
        ie = parse_interaction_event(raw)
        assert ie.is_c2c is True
        assert ie.user_openid == "u789"
        assert ie.operator_openid == "u789"
        assert ie.chat_id == "u789"

    def test_minimal(self):
        ie = parse_interaction_event({})
        assert ie.id == ""
        assert ie.type == 0
        assert ie.data.type == 0
        assert ie.data.resolved.button_data == ""

    def test_guild_scene(self):
        raw = {
            "id": "evt3",
            "type": 11,
            "scene": "guild",
            "channel_id": "ch1",
            "guild_id": "gd1",
            "data": {
                "resolved": {
                    "user_id": "guild_user1",
                },
            },
        }
        ie = parse_interaction_event(raw)
        assert ie.channel_id == "ch1"
        assert ie.guild_id == "gd1"
        assert ie.operator_openid == "guild_user1"
        assert ie.chat_id == "ch1"

    def test_missing_data_field(self):
        """data=None should fall back gracefully."""
        raw = {"id": "evt4", "data": None}
        ie = parse_interaction_event(raw)
        assert ie.data.type == 0
        assert ie.data.resolved.button_data == ""

    def test_missing_resolved_field(self):
        """data.resolved=None should fall back gracefully."""
        raw = {"id": "evt5", "data": {"type": 11, "resolved": None}}
        ie = parse_interaction_event(raw)
        assert ie.data.resolved.button_data == ""
