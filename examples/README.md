# Examples

本目录包含 `qqbot-agent-sdk` 的使用示例。

## 文件说明

| 文件 | 说明 |
|------|------|
| `check_env.py` | 环境检查脚本，验证依赖是否安装正确 |
| `e2e_test.py` | 完整的端到端测试程序（扫码 → 连接 → 交互测试） |
| `config.json.example` | 配置文件模板 |

## 快速开始

```bash
# 1. 检查环境
python examples/check_env.py

# 2. 安装可选依赖（推荐，用于终端显示二维码）
pip install qrcode[pil]

# 3. 运行 E2E 测试
python examples/e2e_test.py
```

## E2E 测试

`e2e_test.py` 是一个完整的端到端测试程序，覆盖 SDK 所有功能：

1. **扫码配置** — 启动后生成二维码，用 QQ 扫码绑定
2. **建立连接** — 自动获取 Token、连接 WebSocket
3. **交互测试** — 在 QQ 中发送命令进行分阶段测试
4. **覆盖率报告** — 发送 `/report` 查看测试覆盖率

### 测试命令

| 命令 | 说明 |
|------|------|
| `/start` | 开始引导式测试 |
| `/next` | 进入下一阶段 |
| `/help` | 查看所有命令 |
| `/report` | 查看覆盖率报告 |
| `/test-text` | 测试纯文本消息 |
| `/test-markdown` | 测试 Markdown 消息 |
| `/test-image` | 测试图片上传 |
| `/test-approval` | 测试审批流程 |

详细命令列表见 E2E 测试程序内的 `/help` 输出。
