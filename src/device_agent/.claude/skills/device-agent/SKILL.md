---
name: device-agent
description: 顶层设备智能体技能。用于理解来自上层生产智能体或本地调试输入的自然语言目标，并按需路由到机器人控制、视觉、任务生成和任务执行技能。
---

# Device Agent

这是设备智能体的顶层技能。它不直接替代底层技能，而是决定何时使用它们。


## 路由规则

- 机器人单步控制：使用 `robot-control`
- 视觉感知、拍照、SAM、GraspNet：使用 `vision-realize`
- 生成 `.claude/tasks/*.json` 工单任务：使用 `task-generator`
- 执行已有 JSON 任务：使用 `task-executor`

## 上层消息处理

生产启动后收到的上层消息不一定都是工单，可能是工单下发、取消、暂停、恢复、状态查询或其它设备指令。先判断消息类型，再决定是否进入具体业务流程。

如果消息是工单下发，再按下面的工单规则处理。

## 工单下发处理

当收到上层工单消息时，先解析完整消息体中的关键字段：

- `device_id`
- `work_order_id`
- `process_id`
- `process_description`
- `instruction` 或其他自然语言执行目标

如果消息中包含 `process_id`，不要自己读取或遍历任务库。直接把工序号交给任务执行器，由 `task_execute.py` 负责匹配任务库中的 JSON 文件。

任务文件可以在顶层声明：

```json
{
  "process_id": "PROC-001",
  "task1": []
}
```

执行规则：

1. 如果上层工单包含 `process_id`，直接使用 `task-executor` 按工序号异步提交任务；执行时带上工单号：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/moveitpy_tools/task_execute.py --process-id <process_id> --work-order-id <work_order_id>
```

2. 如果执行器返回找不到对应 `process_id`，再根据 `process_description` 或 `instruction` 判断是否需要生成新任务、请求补充信息或使用其他技能。
3. 不要在存在 `process_id` 的情况下自己打开任务库查找匹配文件。

## 生产消息处理

生产启动时，输入来源不是终端用户，而是上层生产智能体的异步消息。
当前实现通过 RocketMQ adapter 接收完整上层消息，并转发给 agent。


处理顺序：

1. 判断目标是否属于本设备能力范围。
2. 如果消息是工单下发并且包含 `process_id`，先按“工单下发处理”规则调用任务执行器。
3. 如果找到匹配任务，使用 `task-executor` 异步提交任务。
4. 如果目标不清楚，先用一句话说明缺少的信息。
5. 如果需要感知当前环境，先使用视觉技能。
6. 如果目标是多步任务但没有匹配工序，优先生成或选择 task JSON。
7. 执行任务时，明确说明即将调用的 CLI。
8. 执行完成后，用简短自然语言总结状态、结果和失败原因。

## 状态与心跳

生产启动时，`main.py` 会自动上报设备状态 `connection_state=online,status=idle`，并启动 `device_heartbeat.py` 周期性上报心跳。

调试启动 `main.py --debug` 视为业务离线，只用于本地调试，不发送设备状态更新事件，也不发送心跳。

设备状态事件上报到 `DeviceEventReport`，事件类型为 `device_status_changed`，结构为：

```json
{
  "event_type": "device_status_changed",
  "device_id": "DEV002",
  "connection_state": "online",
  "status": "idle",
  "previous_status": "busy",
  "timestamp": "2026-06-02T10:30:00+08:00"
}
```

设备心跳事件上报到 `DeviceEventReport`，事件类型为 `device_heartbeat`，结构为：

```json
{
  "event_type": "device_heartbeat",
  "device_id": "DEV002",
  "connection_state": "online",
  "status": "idle",
  "timestamp": "2026-06-02T10:30:00+08:00"
}
```

心跳只表示设备智能体仍在线；设备状态变化仍由 `device_status_changed` 表示。

工单状态事件上报到 `DeviceEventReport`，事件类型为 `workorder_status_changed`，只包含以下业务状态：

- `received`: 设备 adapter 从 RocketMQ 收到上层工单消息
- `running`: Claude Agent 已取到该工单，并开始处理或提交执行
- `succeeded`: `task_execute.py` 后台任务执行成功
- `failed`: `task_execute.py` 后台任务执行失败

设备本地 pending 队列只是内部缓存机制，不作为工单业务状态上报。

## 安全约束

- 涉及机械臂运动前，先说明要执行的命令和目的。
- 不要伪造执行结果；CLI 失败时报告失败原因。
- 不要把启动方式切换当成机器人任务执行。
