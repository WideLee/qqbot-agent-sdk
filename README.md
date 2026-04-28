# qqbot-agent-sdk

[![PyPI version](https://img.shields.io/pypi/v/qqbot-agent-sdk.svg)](https://pypi.org/project/qqbot-agent-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/qqbot-agent-sdk.svg)](https://pypi.org/project/qqbot-agent-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Typing: typed](https://img.shields.io/badge/typing-typed-green.svg)](https://peps.python.org/pep-0561/)

QQ Bot 官方机器人 WebSocket Gateway + OpenAPI v2 的独立 Python SDK。

纯 Python 实现，**零 Agent 框架依赖**，仅依赖 `aiohttp`、`httpx` 和 `cryptography`，可集成到任何 Python 项目中。

## 特性

- 🔌 **WebSocket 网关** — 连接、心跳保活、断线自动重连、会话恢复 (Resume)
- 📡 **REST API 客户端** — Token 自动管理、C2C / 群组 / 频道消息发送
- 📎 **附件处理** — 下载、缓存、分片上传、URL 上传、预签名上传
- 🎤 **音频处理** — Silk 格式解码、FFmpeg 转换、语音识别配置
- 🔐 **扫码配置 (Onboard)** — 二维码扫码绑定、AES-GCM 密钥解密
- ✅ **审批流程** — 内联键盘构建、审批按钮交互
- 📦 **完整类型支持** — PEP 561 标记，支持 mypy strict 模式
- 🧪 **单元测试**，覆盖所有模块

## 安装

```bash
pip install qqbot-agent-sdk
```

可选依赖：

```bash
# Silk 音频解码支持
pip install qqbot-agent-sdk[audio]

# 终端二维码渲染（用于 Onboard 扫码流程）
pip install qqbot-agent-sdk[qrcode]

# 安装所有可选依赖
pip install qqbot-agent-sdk[audio,qrcode]
```

## 快速开始

### 基础用法 — 接收消息并回复

```python
import asyncio
from qqbot_agent_sdk import (
    QQApiClient,
    QQWebSocket,
    WSCallbacks,
    EventParser,
    InboundEvent,
)


async def main():
    api = QQApiClient(app_id="YOUR_APP_ID", client_secret="YOUR_SECRET")

    async def on_message(event_type: str, raw: dict):
        event: InboundEvent = EventParser().parse(event_type, raw)
        if event:
            print(f"[{event.chat_scope}] {event.user_name}: {event.content}")
            await api.send_text(
                event.chat_scope,
                event.chat_id,
                f"收到: {event.content}",
                reply_to=event.message_id,
            )

    ws = QQWebSocket(
        callbacks=WSCallbacks(
            on_message_event=on_message,
            get_token=api.ensure_token_sync,
            get_gateway_url=api.get_gateway_url_sync,
        )
    )

    await api.ensure_token()
    gateway_url = await api.get_gateway_url()
    ws.start(gateway_url, asyncio.get_running_loop())

    try:
        await asyncio.Event().wait()  # 保持运行
    finally:
        ws.stop()


asyncio.run(main())
```

### 扫码配置 (Onboard)

无需预先获取 `app_id` 和 `client_secret`，通过扫码自动获取凭据：

```python
import asyncio
from qqbot_agent_sdk import start_onboard


async def onboard():
    def show_qr(url: str):
        print(f"请扫描: {url}")

    result = await start_onboard(on_qr_ready=show_qr)
    print(f"app_id={result.app_id}")
    print(f"secret={result.client_secret}")
    print(f"openid={result.user_openid}")


asyncio.run(onboard())
```

### 发送富媒体消息

```python
from qqbot_agent_sdk import (
    MediaUploader,
    MessageToCreate,
    MediaInfo,
    QQMessageType,
    MEDIA_TYPE_IMAGE,
)

# 上传并发送图片
uploader = MediaUploader(api_client=api, http_client=http_client)
file_info = await uploader.upload(
    chat_type="c2c",
    chat_id=user_openid,
    source="./photo.jpg",
    file_type=MEDIA_TYPE_IMAGE,
)

msg = MessageToCreate(
    msg_type=QQMessageType.RICH_MEDIA,
    msg_seq=api.next_msg_seq(),
    media=MediaInfo(file_info=file_info),
)
await api.post_c2c_message(user_openid, msg)
```

## 核心模块

| 模块 | 说明 |
|------|------|
| `QQApiClient` | REST API 客户端，Token 自动管理、消息发送 |
| `QQWebSocket` | WebSocket 网关，连接 / 心跳 / 重连 / Resume |
| `EventParser` | 将原始 WebSocket 事件解析为 `InboundEvent` |
| `MediaUploader` | 媒体上传（本地文件、URL、分片上传） |
| `MediaLoader` | 媒体加载（文件读取与元信息解析） |
| `AttachmentDownloader` | 附件下载与本地缓存 |
| `AttachmentProcessor` | 附件处理管线 |
| `ApprovalSender` | 审批流程与内联键盘构建 |
| `start_onboard` | 扫码配置高级 API |
| `WSSessionStore` | WebSocket 会话持久化存储 |

## 包结构

```
src/qqbot_agent_sdk/
├── __init__.py          # 公共 API 导出
├── api_client.py        # REST 客户端 + Token 管理
├── websocket.py         # WebSocket 网关生命周期
├── event_parser.py      # 事件解析器
├── dto.py               # 数据传输对象 (dataclass)
├── attachment.py        # 附件下载与处理管线
├── audio.py             # 音频处理 (Silk / FFmpeg / STT)
├── media_loader.py      # 媒体上传工具
├── approval.py          # 审批 / 内联键盘
├── onboard.py           # 扫码配置
├── session_store.py     # 会话持久化
├── constants.py         # 常量与 SDK 配置
├── utils.py             # 工具函数
└── py.typed             # PEP 561 类型标记
```

## 依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `aiohttp` | ≥ 3.9 | WebSocket 连接 |
| `httpx` | ≥ 0.27 | HTTP REST API 调用 |
| `cryptography` | ≥ 42 | Onboard AES-GCM 解密 |
| `pilk` | ≥ 0.2 | *可选* — QQ Silk 音频解码 |
| `qrcode[pil]` | ≥ 7 | *可选* — 终端二维码渲染 |

系统依赖（可选）：`ffmpeg` CLI — 用于音频格式转换。

## 开发

```bash
# 克隆仓库
git clone https://github.com/tencent-connect/qqbot-agent-sdk.git
cd qqbot-agent-sdk

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS

# 安装开发依赖
pip install -e ".[dev,audio,qrcode]"

# 运行测试
pytest

# 类型检查
mypy src/qqbot_agent_sdk

# 代码风格检查
ruff check src/ tests/
```

## 许可证

[MIT](LICENSE)
