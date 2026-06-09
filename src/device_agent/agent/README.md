# Claude Agent SDK Entrypoint

这个目录放自然语言智能体入口。

安装依赖：

```bash
python3 -m pip install -r src/device_agent/agent/requirements.txt
```

启动多轮对话入口：

```bash
python3 src/device_agent/agent/claude_agent_cli.py
```

启动后会显示：

```text
用户:
```

输入自然语言即可和同一个 Claude SDK 会话持续对话。输入 `exit`、`quit`、`退出` 或 `结束` 会结束会话。

默认工作目录是：

```text
/home/lx/dev_ws/src/device_agent
```

这样 SDK 会按 Claude Code 的方式读取 `.claude/skills`、`.claude/settings.local.json` 等项目配置。
