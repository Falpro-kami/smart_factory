# Claude Agent SDK Entrypoint

这个目录放自然语言智能体入口。

安装依赖：

```bash
python3 -m pip install -r src/device_agent/agent/requirements.txt
```

启动生产输入入口：

```bash
python3 src/device_agent/main.py
```

生产输入模式下，设备智能体从本地 adapter 拉取上层消息；adapter 负责对接 RocketMQ。

本地调试入口：

```bash
python3 src/device_agent/main.py --debug
```

调试模式下可直接输入自然语言。输入 `exit`、`quit`、`退出` 或 `结束` 会结束会话。

默认工作目录是：

```text
/home/lx/dev_ws/src/device_agent
```

这样 SDK 会按 Claude Code 的方式读取 `.claude/skills`、`.claude/settings.local.json` 等项目配置。
