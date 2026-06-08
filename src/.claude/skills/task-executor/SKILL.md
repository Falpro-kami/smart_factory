---
name: task-executor
description: 当用户要求执行固定流程任务 JSON 时使用此技能。适用于读取 `.claude/tasks/*.json` 中的步骤列表，顺序执行任务，并在失败时指出具体步骤与修复建议。
---

# Task Executor

该技能用于处理“已经写成 JSON 的流程任务”。

典型触发语句：

- “执行这个 task json”
- “把这个步骤列表跑起来”

## 相关文件

- 任务执行器: `/home/lx/dev_ws/src/moveitpy_tools/task_execute.py`
- 常见任务目录: `/home/lx/dev_ws/src/.claude/tasks`

如果用户只是要执行单条机器人命令，优先使用 `robot_control` skill。
如果用户处理的是“多步 JSON 任务”，优先使用本技能。

## 常用命令

执行整个任务：

```bash
python3 moveitpy_tools/task_execute.py .claude/tasks/task1.json
```

按工序号从任务库自动匹配并执行任务：

```bash
python3 moveitpy_tools/task_execute.py --process-id PROC-001
```

默认是异步提交：命令会立即返回 `job_id`，后台继续执行任务，并由设备侧自动上报工单状态 `running/succeeded/failed`。如果当前消息包含 `work_order_id`，执行时带上它：

```bash
python3 moveitpy_tools/task_execute.py --process-id PROC-001 --work-order-id WO-001
```

只有在明确需要阻塞等待每一步完成时，才使用同步模式：

```bash
python3 moveitpy_tools/task_execute.py .claude/tasks/task1.json --sync
```

设置步间等待时间：

```bash
python3 moveitpy_tools/task_execute.py .claude/tasks/task1.json --delay 0.5
```

## 推荐工作流

处理任务 JSON 时，按下面顺序做：

1. 如果有 `process_id`，优先使用 `task_execute.py --process-id <process_id>` 异步提交任务
2. 记录返回的 `job_id`
3. 告知用户/上层任务已提交，后台执行结果会通过设备状态事件上报

## 失败处理

如果任务执行失败，应向用户反馈：

- 出错的步骤序号
- 对应命令
- stderr 中的关键报错
- 下一步建议

## 输出要求

- 如果只是“把 JSON 转成命令”，直接给命令
- 如果只是“检查任务”，优先给校验结果和风险点
- 如果是“执行任务”，简洁说明正在执行哪个文件，再汇报每一步结果
- 不要输出冗长推理
