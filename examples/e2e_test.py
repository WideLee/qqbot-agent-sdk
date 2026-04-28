#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQBot SDK 端到端测试

完整的 E2E 测试流程:
1. 扫码配置 (onboard)
2. 建立 WebSocket 连接
3. 引导用户测试所有功能
4. 自动回复各种类型的消息
5. 覆盖所有 SDK 内部流程

运行方式:
    python e2e_test.py
"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Set

import httpx

from qqbot_agent_sdk import (
    # Core
    QQApiClient,
    QQWebSocket,
    WSCallbacks,
    EventParser,
    InboundEvent,
    
    # Onboard
    BindStatus,
    OnboardResult,
    start_onboard,
    
    # Attachment & Media
    AttachmentDownloader,
    AttachmentProcessor,
    MediaLoader,
    MediaUploader,
    describe_attachment,
    UploadDailyLimitExceededError,
    UploadFileTooLargeError,
    
    # Approval
    ApprovalRequest,
    ApprovalSender,
    parse_approval_button_data,
    
    # Session
    WSSessionStore,
    
    # DTOs
    EventType,
    MessageToCreate,
    QQMessageType,
    MediaInfo,
    InlineKeyboard,
    parse_interaction_event,
    GuildMessageToCreate,
    InputNotify,
    
    # Constants
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VOICE,
    MEDIA_TYPE_FILE,
    MAX_MESSAGE_LENGTH,
    
    # Utils
    parse_qq_timestamp,
    is_fatal_send_error,
    build_user_agent,
)

# 导入未在 __init__.py 中导出的类型
from qqbot_agent_sdk.dto import (
    MSG_TYPE_QUOTE,
    MessageReference,
    KeyboardButton,
    KeyboardButtonAction,
    KeyboardButtonRenderData,
    KeyboardRow,
    KeyboardContent,
)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


class E2ETest:
    """端到端测试"""
    
    def __init__(self, app_id: str, client_secret: str, user_openid: str):
        self.app_id = app_id
        self.client_secret = client_secret
        self.user_openid = user_openid
        
        # HTTP 客户端
        self.http_client = httpx.AsyncClient(timeout=60.0)
        
        # API 客户端
        self.api = QQApiClient(app_id, client_secret, log_tag="E2E")
        self.api.setup(self.http_client)
        
        # 测试目录
        self.test_dir = Path("./e2e_test_files")
        self.test_dir.mkdir(exist_ok=True)
        
        # 组件
        self.event_parser = EventParser()
        self.attachment_downloader = AttachmentDownloader(
            self.http_client,
            cache_dir=str(self.test_dir / "attachments"),
            log_tag="E2E",
        )
        self.attachment_processor = AttachmentProcessor(self.attachment_downloader)
        # MediaLoader 是静态类，不需要实例化
        self.media_uploader = MediaUploader(self.api, self.http_client, log_tag="E2E")
        self.approval_sender = ApprovalSender(self.api, log_tag="E2E")
        # WSSessionStore 需要目录路径，不是文件路径
        self.session_store = WSSessionStore(base_dir=".", filename="e2e_session.json")
        
        # WebSocket
        self.ws: Optional[QQWebSocket] = None
        
        # 测试状态
        self.tested_features: Set[str] = set()
        self.pending_approvals: Dict[str, tuple] = {}
        
        # 测试向导状态
        self.welcomed = False
        self.current_stage = 0  # 当前测试阶段
        self.test_stages = [
            {
                "name": "基础消息",
                "commands": ["/test-text", "/test-markdown", "/test-quote", "/test-long"],
                "description": "测试文本消息的各种形式",
            },
            {
                "name": "富媒体上传",
                "commands": ["/test-image", "/test-file", "/test-url"],
                "description": "测试图片、文件上传功能",
            },
            {
                "name": "交互功能",
                "commands": ["/test-approval", "/test-keyboard"],
                "description": "测试审批流程和自定义键盘",
            },
            {
                "name": "附件处理",
                "commands": ["发送图片", "发送语音", "发送文件"],
                "description": "测试附件下载和处理功能",
            },
            {
                "name": "高级功能",
                "commands": ["/test-typing", "/test-batch", "/test-retry"],
                "description": "测试输入状态、批量发送等高级功能",
            },
        ]
    
    async def run(self):
        """运行完整测试"""
        try:
            # 初始化
            await self.api.ensure_token()
            logger.info("✓ Token 获取成功")
            self.tested_features.add("api_token")
            
            # 启动 WebSocket - 传入当前事件循环
            self.start_websocket(asyncio.get_running_loop())
            logger.info("✓ WebSocket 已启动")
            
            # 发送首条消息给测试者
            await self.send_initial_message()
            
            # 保持运行
            logger.info("\n" + "="*70)
            logger.info("E2E 测试运行中...")
            logger.info("请在 QQ 中向机器人发送消息开始测试")
            logger.info("按 Ctrl+C 退出")
            logger.info("="*70)
            
            while True:
                await asyncio.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("\n退出测试...")
        
        finally:
            await self.cleanup()
    
    async def send_initial_message(self):
        """发送初始测试消息给配置者"""
        if not self.user_openid:
            logger.warning("未设置 user_openid，跳过初始消息")
            return
        
        try:
            welcome = """
# 🎉 QQBot SDK E2E 测试已启动

欢迎使用 QQBot SDK 端到端测试程序！

## 📋 测试流程

本测试分为 5 个阶段，每完成一个阶段会自动引导下一阶段：

1️⃣ **基础消息** - 文本、Markdown、引用、长文本
2️⃣ **富媒体上传** - 图片、文件、URL 上传
3️⃣ **交互功能** - 审批流程、自定义键盘
4️⃣ **附件处理** - 发送图片/语音/文件测试下载
5️⃣ **高级功能** - 输入状态、批量发送等

## 🚀 开始测试

发送 `/start` 开始第一阶段测试
发送 `/help` 查看所有命令
发送任意消息我会回复你
            """.strip()
            
            await self.api.send_text(
                "c2c",
                self.user_openid,
                welcome,
                markdown=True,
            )
            logger.info(f"✓ 初始消息已发送到 {self.user_openid}")
        except Exception as exc:
            logger.warning(f"发送初始消息失败: {exc}")
    
    def start_websocket(self, main_loop: asyncio.AbstractEventLoop):
        """启动 WebSocket
        
        Args:
            main_loop: 主事件循环,用于执行异步回调
        """
        def get_session_tuple():
            """获取会话信息，返回 (session_id, seq) 元组"""
            session = self.session_store.get(self.app_id)
            if session.is_resumable and session.is_fresh():
                return (session.session_id, session.seq)
            return (None, None)
        
        def save_session_tuple(session_id, seq):
            """保存会话信息"""
            if session_id:
                self.session_store.save(self.app_id, session_id, seq)
        
        callbacks = WSCallbacks(
            on_message_event=self.on_message_event,
            on_interaction_event=self.on_interaction_event,
            on_connected=lambda: logger.info("✓ WebSocket 已连接"),
            on_disconnected=lambda: logger.warning("WebSocket 已断开"),
            on_fatal_error=lambda c, m: logger.error(f"错误 [{c}]: {m}"),
            get_token=self.api.ensure_token_sync,
            get_gateway_url=self.api.get_gateway_url_sync,
            get_session=get_session_tuple,
            set_session=save_session_tuple,
            set_heartbeat_interval=lambda interval: logger.debug(f"心跳间隔: {interval}s"),
            clear_token=self.api.clear_token,
            fail_pending=lambda reason: logger.warning(f"失败挂起请求: {reason}"),
            on_heartbeat_ack=lambda: self.tested_features.add("heartbeat"),
        )
        
        self.ws = QQWebSocket(callbacks=callbacks, log_tag="E2E")
        gateway_url = self.api.get_gateway_url_sync()
        # 使用主事件循环,而不是创建新循环
        self.ws.start(gateway_url, main_loop)
        
        self.tested_features.add("websocket_connect")
    
    async def on_message_event(self, event_type: str, raw: dict):
        """处理消息事件"""
        event = self.event_parser.parse(event_type, raw)
        if not event:
            return
        
        self.tested_features.add("event_parser")
        self.tested_features.add(f"event_{event.chat_scope}")
        
        logger.info(f"\n收到消息 [{event.chat_scope}] {event.user_name or event.user_id}: {event.content[:50]}")
        
        # 首次消息 - 发送测试指南
        if not self.welcomed:
            await self.send_test_guide(event)
            self.welcomed = True
            return
        
        # 处理命令
        content = event.content.strip()
        
        if content == "/start":
            await self.start_guided_test(event)
        elif content == "/next":
            await self.next_stage(event)
        elif content == "/help":
            await self.send_test_guide(event)
        elif content == "/report":
            await self.show_test_report(event)
        elif content == "/test-text":
            await self.test_text_message(event)
        elif content == "/test-markdown":
            await self.test_markdown_message(event)
        elif content == "/test-quote":
            await self.test_quote_message(event)
        elif content == "/test-long":
            await self.test_long_message(event)
        elif content == "/test-image":
            await self.test_image_upload(event)
        elif content == "/test-file":
            await self.test_file_upload(event)
        elif content == "/test-url":
            await self.test_url_upload(event)
        elif content == "/test-approval":
            await self.test_approval_flow(event)
        elif content == "/test-keyboard":
            await self.test_custom_keyboard(event)
        elif content == "/test-typing" and event.chat_scope == "c2c":
            await self.test_typing_indicator(event)
        elif content == "/test-batch":
            await self.test_batch_send(event)
        elif content == "/test-retry":
            await self.test_retry_mechanism(event)
        elif content == "/test-video":
            await self.test_video_upload(event)
        elif content == "/test-voice":
            await self.test_voice_upload(event)
        elif content == "/test-guild":
            await self.test_guild_message(event)
        elif content == "/test-chunked":
            await self.test_chunked_upload(event)
        elif content == "/test-reconnect":
            await self.test_reconnect(event)
        elif content == "/test-resume":
            await self.test_resume(event)
        elif content == "/report":
            await self.show_test_report(event)
        elif content.startswith("/"):
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"❌ 未知命令: {content}\n发送 /help 查看可用命令",
                reply_to=event.message_id,
            )
        else:
            # 普通消息 - 回声 + 附件处理
            await self.handle_normal_message(event)
    
    async def on_interaction_event(self, event_type: str, raw: dict):
        """处理交互事件(按钮点击)"""
        interaction = parse_interaction_event(raw)
        logger.info(f"收到交互: {interaction.data.resolved.button_data}")
        
        # 确认交互
        await self.api.acknowledge_interaction(interaction.id)
        self.tested_features.add("interaction_ack")
        
        # 解析审批按钮
        parsed = parse_approval_button_data(interaction.data.resolved.button_data)
        if parsed:
            session_key, decision = parsed
            await self.handle_approval_response(session_key, decision, interaction)
            return
        
        # 自定义键盘
        if interaction.data.resolved.button_data.startswith("test_keyboard:"):
            choice = interaction.data.resolved.button_data.split(":")[-1]
            chat_type = "c2c" if interaction.is_c2c else "group"
            await self.api.send_text(
                chat_type,
                interaction.chat_id,
                f"✓ 你选择了: {choice.upper()}",
            )
            self.tested_features.add("keyboard_click")
    
    async def handle_approval_response(self, session_key: str, decision: str, interaction):
        """处理审批响应"""
        if session_key not in self.pending_approvals:
            return
        
        chat_type, chat_id = self.pending_approvals.pop(session_key)
        
        responses = {
            "allow-once": "✅ 已允许一次",
            "allow-always": "⭐ 已始终允许",
            "deny": "❌ 已拒绝",
        }
        
        await self.api.send_text(
            chat_type,
            chat_id,
            responses.get(decision, f"❓ {decision}"),
        )
        
        self.tested_features.add("approval_response")
        logger.info(f"✓ 审批响应: {decision}")
    
    async def send_test_guide(self, event: InboundEvent):
        """发送测试指南"""
        guide = """
# 🧪 QQBot SDK E2E 测试指南

## 🎯 推荐方式：引导式测试

发送 `/start` 开始分阶段引导测试
程序会自动带你完成所有测试项目

## 📋 手动测试命令

### 基础消息
- `/test-text` - 纯文本消息
- `/test-markdown` - Markdown 消息
- `/test-quote` - 引用回复
- `/test-long` - 长文本截断

### 富媒体上传
- `/test-image` - 图片上传
- `/test-file` - 文件上传
- `/test-url` - URL 上传
- `/test-video` - 视频上传
- `/test-chunked` - 分片上传(大文件)

### 交互功能
- `/test-approval` - 审批流程(按钮交互)
- `/test-keyboard` - 自定义键盘

### 附件测试
- 发送图片 -> 自动下载分析
- 发送语音 -> 自动处理转写
- 发送文件 -> 自动保存

### 高级功能
- `/test-typing` - 输入状态(仅 C2C)
- `/test-batch` - 批量发送
- `/test-retry` - 重试机制

### 其他
- `/report` - 测试覆盖率报告
- `/next` - 引导模式下进入下一阶段
- `/help` - 显示本指南

💡 发送普通消息会收到回声
        """.strip()
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            guide,
            reply_to=event.message_id,
            markdown=True,
        )
        
        self.tested_features.add("send_markdown")
    
    async def handle_normal_message(self, event: InboundEvent):
        """处理普通消息"""
        # 引用消息 - 回显被引用的原文
        if event.message_type == MSG_TYPE_QUOTE and event.msg_elements:
            quoted = event.msg_elements[0]
            reply_parts = [f"收到: {event.content}"]
            reply_parts.append(f"\n📎 引用原文: {quoted.content}" if quoted.content else "\n📎 引用原文: (无文字)")
            if quoted.attachments:
                att_names = [a.filename for a in quoted.attachments]
                reply_parts.append(f"📎 引用附件: {', '.join(att_names)}")
            
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                "\n".join(reply_parts),
                reply_to=event.message_id,
            )
            self.tested_features.add("quote_echo")
        else:
            # 普通消息 - 回声
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"收到: {event.content}",
                reply_to=event.message_id,
            )
        
        self.tested_features.add("send_text")
        
        # 处理附件
        if event.attachments:
            await self.process_attachments(event)
    
    async def process_attachments(self, event: InboundEvent):
        """处理附件 - 下载后重新上传发送回去"""
        # 确保 attachments 是列表
        attachments = event.attachments if isinstance(event.attachments, list) else [event.attachments]
        
        # ── 调试: 打印收到的原始附件信息 ──
        logger.info("=" * 60)
        logger.info(f"📥 收到 {len(attachments)} 个附件")
        logger.info(f"   event.attachments type: {type(event.attachments)}")
        for i, att in enumerate(attachments):
            logger.info(f"   [{i}] type={type(att).__name__}")
            logger.info(f"       filename     = {att.filename!r}")
            logger.info(f"       content_type  = {att.content_type!r}")
            logger.info(f"       resolved_url  = {att.resolved_url[:80]!r}..." if len(att.resolved_url) > 80 else f"       resolved_url  = {att.resolved_url!r}")
            logger.info(f"       asr_refer_text= {att.asr_refer_text!r}")
        logger.info("=" * 60)
        
        for att in attachments:
            try:
                content_type = att.content_type.strip().lower()
                
                # 1. 下载附件到本地
                # 语音文件不走 AttachmentProcessor（需要 STT），直接用 downloader 下载
                if content_type.startswith("audio") or att.filename.endswith((".amr", ".silk")):
                    local_path_str = await self.attachment_downloader.download_document(
                        att.resolved_url, att.filename,
                    )
                    if not local_path_str:
                        logger.warning(f"⚠️ 语音下载失败: {att.filename}")
                        await self.api.send_text(
                            event.chat_scope,
                            event.chat_id,
                            f"⚠️ 语音下载失败: {att.filename}",
                            reply_to=event.message_id,
                        )
                        continue
                    local_path = Path(local_path_str)
                    logger.info(f"✓ 语音已下载: {att.filename} → {local_path}")
                else:
                    # 图片/视频/文档走 AttachmentProcessor
                    results = await self.attachment_processor.process([att])
                    
                    if not results:
                        logger.warning(f"⚠️ 附件处理返回空结果: {att.filename}")
                        await self.api.send_text(
                            event.chat_scope,
                            event.chat_id,
                            f"⚠️ 无法处理附件: {att.filename}",
                            reply_to=event.message_id,
                        )
                        continue
                    
                    processed = results[0]
                    logger.info(f"📦 处理结果: kind={processed.kind}, local_path={processed.local_path}")
                    
                    local_path = Path(processed.local_path)
                    if not local_path.exists():
                        logger.error(f"❌ 本地文件不存在: {local_path}")
                        continue
                
                self.tested_features.add("attachment_download")
                file_size = local_path.stat().st_size
                logger.info(f"✓ 已下载: {att.filename} → {local_path} ({file_size} 字节)")
                
                # 3. 语音识别 - 回显 QQ 服务端的 ASR 结果（不依赖本地 STT）
                if content_type.startswith("audio") or att.filename.endswith((".amr", ".silk")):
                    if att.asr_refer_text:
                        self.tested_features.add("voice_asr")
                        await self.api.send_text(
                            event.chat_scope,
                            event.chat_id,
                            f"🎤 语音识别: {att.asr_refer_text}",
                            reply_to=event.message_id,
                        )
                    else:
                        await self.api.send_text(
                            event.chat_scope,
                            event.chat_id,
                            "🎤 收到语音消息（无识别文本）",
                            reply_to=event.message_id,
                        )
                
                # 4. 确定上传类型（content_type 在循环开头已定义）
                if content_type.startswith("image"):
                    file_type = MEDIA_TYPE_IMAGE
                elif content_type.startswith("video"):
                    file_type = MEDIA_TYPE_VIDEO
                elif content_type.startswith("audio"):
                    file_type = MEDIA_TYPE_VOICE
                else:
                    file_type = MEDIA_TYPE_FILE
                
                # ── 调试: 打印上传请求参数 ──
                logger.info("📤 上传请求:")
                logger.info(f"   chat_type = {event.chat_scope!r}")
                logger.info(f"   chat_id   = {event.chat_id!r}")
                logger.info(f"   source    = {str(local_path)!r}")
                logger.info(f"   file_type = {file_type} (content_type={content_type!r})")
                
                # 5. 用本地文件重新上传
                file_info = await self.media_uploader.upload(
                    chat_type=event.chat_scope,
                    chat_id=event.chat_id,
                    source=str(local_path),
                    file_type=file_type,
                )
                
                logger.info(f"✓ 上传成功, file_info={file_info[:80]}..." if len(file_info) > 80 else f"✓ 上传成功, file_info={file_info}")
                
                # 6. 发送富媒体消息
                msg = MessageToCreate(
                    msg_type=QQMessageType.RICH_MEDIA,
                    msg_seq=self.api.next_msg_seq(),
                    msg_id=event.message_id,
                    media=MediaInfo(file_info=file_info),
                )
                
                # ── 调试: 打印发送消息体 ──
                logger.info(f"📨 发送消息: msg_type={msg.msg_type}, msg_id={msg.msg_id}")
                
                if event.chat_scope == "c2c":
                    resp = await self.api.post_c2c_message(event.chat_id, msg)
                else:
                    resp = await self.api.post_group_message(event.chat_id, msg)
                
                logger.info(f"✓ 已回显: {att.filename}")
            
            except Exception as exc:
                import traceback
                logger.error(f"附件处理失败: {exc}")
                logger.error(traceback.format_exc())
                await self.api.send_text(
                    event.chat_scope,
                    event.chat_id,
                    f"❌ 处理 {att.filename} 失败: {exc}",
                    reply_to=event.message_id,
                )
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 测试用例
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def test_text_message(self, event: InboundEvent):
        """测试纯文本消息"""
        msg = MessageToCreate(
            content="纯文本消息 (msg_type=0)",
            msg_type=QQMessageType.TEXT,
            msg_seq=self.api.next_msg_seq(),
            msg_id=event.message_id,
        )
        
        if event.chat_scope == "c2c":
            await self.api.post_c2c_message(event.chat_id, msg)
        else:
            await self.api.post_group_message(event.chat_id, msg)
        
        self.tested_features.add("msg_type_text")
        logger.info("✓ 纯文本消息测试完成")
    
    async def test_markdown_message(self, event: InboundEvent):
        """测试 Markdown 消息"""
        markdown = """
# Markdown 测试

**粗体** *斜体* `代码`

```python
print("Hello!")
```

> 引用

✓ Markdown 测试完成
        """.strip()
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            markdown,
            reply_to=event.message_id,
            markdown=True,
        )
        
        self.tested_features.add("msg_type_markdown")
        logger.info("✓ Markdown 消息测试完成")
    
    async def test_quote_message(self, event: InboundEvent):
        """测试引用回复 — 回显被引用的原始内容"""
        quoted_content = event.content.strip()
        # 去掉命令本身，如果用户只发了 /test-quote 则显示命令文本
        display = quoted_content if quoted_content != "/test-quote" else "/test-quote"

        msg = MessageToCreate(
            content=f"📎 引用你的消息: {display}",
            msg_type=QQMessageType.TEXT,
            msg_seq=self.api.next_msg_seq(),
            msg_id=event.message_id,
            message_reference=MessageReference(message_id=event.message_id),
        )
        
        if event.chat_scope == "c2c":
            await self.api.post_c2c_message(event.chat_id, msg)
        else:
            await self.api.post_group_message(event.chat_id, msg)
        
        self.tested_features.add("message_reference")
        logger.info("✓ 引用回复测试完成")
    
    async def test_long_message(self, event: InboundEvent):
        """测试长文本截断"""
        long_text = "测试长文本截断。" * 500
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            long_text,
            reply_to=event.message_id,
            max_length=MAX_MESSAGE_LENGTH,
        )
        
        self.tested_features.add("text_truncate")
        logger.info("✓ 长文本截断测试完成")
    
    async def test_image_upload(self, event: InboundEvent):
        """测试图片上传"""
        test_image = self.test_dir / "test.png"
        
        # 如果测试图片不存在，创建一个简单文本文件作为占位
        if not test_image.exists():
            test_image.write_text("test image placeholder", encoding="utf-8")
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            "⏳ 上传中...",
            reply_to=event.message_id,
        )
        
        try:
            # MediaUploader.upload() 参数: source, file_type
            file_info = await self.media_uploader.upload(
                chat_type=event.chat_scope,
                chat_id=event.chat_id,
                source=str(test_image),
                file_type=MEDIA_TYPE_IMAGE,
            )
            
            msg = MessageToCreate(
                msg_type=QQMessageType.RICH_MEDIA,
                msg_seq=self.api.next_msg_seq(),
                msg_id=event.message_id,
                media=MediaInfo(file_info=file_info),
            )
            
            if event.chat_scope == "c2c":
                await self.api.post_c2c_message(event.chat_id, msg)
            else:
                await self.api.post_group_message(event.chat_id, msg)
            
            self.tested_features.add("upload_image")
            logger.info("✓ 图片上传测试完成")
        
        except Exception as exc:
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"❌ 上传失败: {exc}",
                reply_to=event.message_id,
            )
    
    async def test_file_upload(self, event: InboundEvent):
        """测试文件上传"""
        test_file = self.test_dir / "test.txt"
        test_file.write_text(f"E2E Test\nTime: {time.time()}\n", encoding="utf-8")
        
        try:
            # MediaUploader.upload() 参数: source, file_type
            file_info = await self.media_uploader.upload(
                chat_type=event.chat_scope,
                chat_id=event.chat_id,
                source=str(test_file),
                file_type=MEDIA_TYPE_FILE,
            )
            
            msg = MessageToCreate(
                msg_type=QQMessageType.RICH_MEDIA,
                msg_seq=self.api.next_msg_seq(),
                msg_id=event.message_id,
                media=MediaInfo(file_info=file_info),
            )
            
            if event.chat_scope == "c2c":
                await self.api.post_c2c_message(event.chat_id, msg)
            else:
                await self.api.post_group_message(event.chat_id, msg)
            
            self.tested_features.add("upload_file")
            logger.info("✓ 文件上传测试完成")
        
        except Exception as exc:
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"❌ 上传失败: {exc}",
                reply_to=event.message_id,
            )
    
    async def test_url_upload(self, event: InboundEvent):
        """测试 URL 上传"""
        url = "https://picsum.photos/400/300"
        
        try:
            # MediaUploader.upload() 参数: source, file_type (不是 media_type)
            file_info = await self.media_uploader.upload(
                chat_type=event.chat_scope,
                chat_id=event.chat_id,
                source=url,
                file_type=MEDIA_TYPE_IMAGE,
            )
            
            msg = MessageToCreate(
                msg_type=QQMessageType.RICH_MEDIA,
                msg_seq=self.api.next_msg_seq(),
                msg_id=event.message_id,
                media=MediaInfo(file_info=file_info),
            )
            
            if event.chat_scope == "c2c":
                await self.api.post_c2c_message(event.chat_id, msg)
            else:
                await self.api.post_group_message(event.chat_id, msg)
            
            self.tested_features.add("upload_url")
            logger.info("✓ URL 上传测试完成")
        
        except Exception as exc:
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"❌ URL 上传失败: {exc}",
                reply_to=event.message_id,
            )
    
    async def test_approval_flow(self, event: InboundEvent):
        """测试审批流程"""
        session_key = f"e2e_{event.message_id}"
        
        approval = ApprovalRequest(
            session_key=session_key,
            title="E2E 测试审批",
            description="请点击按钮测试交互功能",
            command_preview="echo 'test'",
            cwd=str(Path.cwd()),
            severity="info",
            timeout_sec=60,
        )
        
        self.pending_approvals[session_key] = (event.chat_scope, event.chat_id)
        
        success = await self.approval_sender.send(
            chat_type=event.chat_scope,
            chat_id=event.chat_id,
            req=approval,
            msg_id=event.message_id,
        )
        
        if success:
            self.tested_features.add("approval_send")
            logger.info("✓ 审批消息已发送")
    
    async def test_custom_keyboard(self, event: InboundEvent):
        """测试自定义键盘"""
        keyboard = InlineKeyboard(
            content=KeyboardContent(
                rows=[
                    KeyboardRow(buttons=[
                        KeyboardButton(
                            id="btn_a",
                            render_data=KeyboardButtonRenderData(
                                label="选项 A",
                                visited_label="已选 A",
                                style=1,
                            ),
                            action=KeyboardButtonAction(
                                type=1,
                                data="test_keyboard:a",
                            ),
                        ),
                        KeyboardButton(
                            id="btn_b",
                            render_data=KeyboardButtonRenderData(
                                label="选项 B",
                                visited_label="已选 B",
                                style=0,
                            ),
                            action=KeyboardButtonAction(
                                type=1,
                                data="test_keyboard:b",
                            ),
                        ),
                    ]),
                ]
            )
        )
        
        msg = self.api.build_text_body("请选择:", reply_to=event.message_id, markdown=True)
        
        if event.chat_scope == "c2c":
            await self.api.post_c2c_message(event.chat_id, msg, keyboard=keyboard)
        else:
            await self.api.post_group_message(event.chat_id, msg, keyboard=keyboard)
        
        self.tested_features.add("custom_keyboard")
        logger.info("✓ 自定义键盘测试完成")
    
    async def test_typing_indicator(self, event: InboundEvent):
        """测试输入状态"""
        await self.api.send_typing(
            chat_id=event.chat_id,
            msg_id=event.message_id,
            input_seconds=5,
        )
        
        self.tested_features.add("typing_indicator")
        await asyncio.sleep(3)
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            "✓ 输入状态测试完成",
            reply_to=event.message_id,
        )
    
    async def test_batch_send(self, event: InboundEvent):
        """测试批量发送"""
        for i in range(3):
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                f"批量消息 {i+1}/3",
            )
            await asyncio.sleep(0.5)
        
        self.tested_features.add("batch_send")
        logger.info("✓ 批量发送测试完成")
    
    async def test_retry_mechanism(self, event: InboundEvent):
        """测试重试机制"""
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            "测试重试机制(已启用自动重试)",
            reply_to=event.message_id,
            retries=3,
        )
        
        self.tested_features.add("retry_mechanism")
        logger.info("✓ 重试机制测试完成")
    
    async def start_guided_test(self, event: InboundEvent):
        """开始引导式测试"""
        self.current_stage = 0
        await self.send_stage_guide(event)
    
    async def next_stage(self, event: InboundEvent):
        """进入下一个测试阶段"""
        self.current_stage += 1
        
        if self.current_stage >= len(self.test_stages):
            await self.api.send_text(
                event.chat_scope,
                event.chat_id,
                "🎉 恭喜！所有测试阶段已完成！\n\n发送 /report 查看最终测试报告",
                reply_to=event.message_id,
                markdown=True,
            )
            return
        
        await self.send_stage_guide(event)
    
    async def send_stage_guide(self, event: InboundEvent):
        """发送当前阶段的测试指南"""
        if self.current_stage >= len(self.test_stages):
            return
        
        stage = self.test_stages[self.current_stage]
        stage_num = self.current_stage + 1
        total = len(self.test_stages)
        
        guide = f"""
# 📍 第 {stage_num}/{total} 阶段: {stage['name']}

{stage['description']}

## 🎯 本阶段测试项目

"""
        
        for cmd in stage["commands"]:
            if cmd.startswith("/"):
                guide += f"- `{cmd}`\n"
            else:
                guide += f"- {cmd}\n"
        
        guide += f"""

## 💡 操作提示

{self._get_stage_tips(stage_num)}

完成后发送 `/next` 进入下一阶段
发送 `/report` 查看当前进度
        """.strip()
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            guide,
            reply_to=event.message_id,
            markdown=True,
        )
        
        logger.info(f"✓ 已发送第 {stage_num} 阶段测试指南")
    
    def _get_stage_tips(self, stage_num: int) -> str:
        """获取阶段提示"""
        tips = {
            1: "依次发送每个命令,观察机器人的回复效果",
            2: "每个命令会触发不同的文件上传方式,注意观察上传过程",
            3: "点击审批按钮和自定义键盘按钮,体验交互功能",
            4: "直接发送图片、语音或文件,测试附件下载和处理",
            5: "这些是高级功能,部分功能仅在特定场景可用",
        }
        return tips.get(stage_num, "按照提示完成测试")
    
    async def show_test_report(self, event: InboundEvent):
        """显示测试报告"""
        all_features = {
            "api_token", "websocket_connect", "event_parser",
            "send_text", "send_markdown", "msg_type_text", "msg_type_markdown",
            "message_reference", "text_truncate",
            "upload_image", "upload_file", "upload_url",
            "approval_send", "approval_response",
            "custom_keyboard", "keyboard_click",
            "attachment_download", "voice_asr",
            "typing_indicator", "batch_send", "retry_mechanism",
            "heartbeat", "session_persist",
        }
        
        tested = self.tested_features
        coverage = len(tested) / len(all_features) * 100
        
        report = f"""
# 📊 测试覆盖率报告

## 总体覆盖率: {coverage:.1f}%
已测试: {len(tested)} / {len(all_features)} 项

## ✅ 已测试功能
{chr(10).join(f"- {f}" for f in sorted(tested))}

## ⏳ 未测试功能
{chr(10).join(f"- {f}" for f in sorted(all_features - tested))}

继续发送测试命令完成剩余测试！
        """.strip()
        
        await self.api.send_text(
            event.chat_scope,
            event.chat_id,
            report,
            reply_to=event.message_id,
            markdown=True,
        )
    
    async def cleanup(self):
        """清理资源"""
        if self.ws:
            self.ws.stop()
        await self.http_client.aclose()
        
        # 保存最终报告
        report = {
            "tested_features": list(self.tested_features),
            "timestamp": time.time(),
        }
        Path("e2e_report.json").write_text(json.dumps(report, indent=2))
        logger.info(f"✓ 测试报告已保存: e2e_report.json")


async def run_onboard():
    """运行扫码配置"""
    def show_qr(url: str):
        """显示二维码"""
        print("\n" + "="*70)
        print("📱 请使用 QQ 扫描以下二维码")
        print("="*70 + "\n")
        
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=1,
                border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            
            # 在终端打印二维码
            qr.print_ascii(invert=True)
            
        except ImportError:
            print("⚠️  未安装 qrcode 库，无法显示二维码")
            print("💡 安装方法: pip install qrcode[pil]")
            print(f"\n或直接访问: {url}\n")
        
        print("\n" + "="*70)
        print("⏳ 等待扫码授权...")
        print("="*70 + "\n")
    
    # 使用 start_onboard 高级 API
    result = await start_onboard(
        on_qr_ready=show_qr,
        poll_interval=2,
        poll_timeout=300,
    )
    
    print("\n" + "="*70)
    print("✅ 扫码授权成功!")
    print("="*70)
    print(f"🤖 App ID:      {result.app_id}")
    print(f"👤 User OpenID: {result.user_openid}")
    print("="*70 + "\n")
    
    return result.app_id, result.client_secret, result.user_openid


async def main():
    """主程序"""
    print("\n" + "🚀 " + "="*66 + " 🚀")
    print("   QQBot SDK E2E 端到端测试程序")
    print("🚀 " + "="*66 + " 🚀\n")
    
    # 步骤 1: 扫码配置
    print("📍 步骤 1/2: 扫码配置\n")
    app_id, client_secret, user_openid = await run_onboard()
    
    # 步骤 2: 运行测试
    print("📍 步骤 2/2: 启动 E2E 测试\n")
    print("="*70)
    print("🔌 正在连接 WebSocket...")
    print("="*70 + "\n")
    
    test = E2ETest(app_id, client_secret, user_openid)
    await test.run()


if __name__ == "__main__":
    asyncio.run(main())
