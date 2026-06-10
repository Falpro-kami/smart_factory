---
name: task-generator
description: 当用户希望根据一个未知目标进行示教、自动规划任务步骤、结合视觉理解和机器人控制生成 `.claude/tasks/*.json` 任务文件时使用该技能。适用于先看懂场景、识别目标物体与相对位置，再把目标拆成抓取、移动、放置等操作序列。
---

# Task Generator

该技能用于“示教”和“任务生成”，目标是把自然语言任务转成可执行的 task JSON。

适用场景：

- “帮我生成一个 task 文件”
- “教 agent 完成这个未知任务”
- “根据当前桌面场景自动拆解步骤”
- “先看图识别物体，再生成抓取搬运流程”
- “把这个任务写成 `.claude/tasks/*.json`”

如果用户已经有现成 task JSON，要执行它，优先使用 `task_executor` skill。
如果用户只是要单步运动控制，优先使用 `robot_control` skill。
如果用户只是要抓图、分割、视觉问答，优先使用 `vision_realize` skill。

## 相关文件

- 任务目录: `/home/lx/smart_factory/src/device_agent/.claude/tasks`
- 任务执行器: `/home/lx/smart_factory/src/device_agent/moveitpy_tools/task_execute.py`
- 机器人控制 skill: `/home/lx/smart_factory/src/device_agent/.claude/skills/robot-control/SKILL.md`
- 视觉 skill: `/home/lx/smart_factory/src/device_agent/.claude/skills/vision-realize/SKILL.md`

## 目标

把用户给出的目标描述，转成一个新的 JSON 任务文件，通常保存在：

```text
/home/lx/smart_factory/src/device_agent/.claude/tasks/task_<name>.json
```

生成的 JSON 要兼容现有 `task_execute.py` 风格。

## 已知任务格式

任务文件的顶层格式是：

```json
{
  "task_name": [
    {
      "operation": "PTP",
      "parameters": {
        "x": 0.0,
        "y": -0.8,
        "z": 0.95,
        "roll": 3.14,
        "pitch": 0.0,
        "yaw": -3.14
      }
    },
    {
      "operation": "LIN",
      "parameters": {
        "frame": "tool_frame",
        "dz": 0.12
      }
    },
    {
      "operation": "grasp",
      "parameters": {
        "state": 1
      }
    },
    {
      "operation": "HOME"
    }
  ]
}
```

常见操作：

- `HOME`
- `PTP`
- `LIN`
- `grasp`

## 推荐工作流

生成任务时，优先按下面顺序做：

1. 先明确用户目标
2. 如果物体位置、类别、堆叠关系未知，先调用 `vision_realize` 获取当前场景信息
3. 把任务拆成一系列“抓取源位置 -> 抬升 -> 移动到目标位置 -> 放下”的原子动作
4. 把每个原子动作写成 `PTP`、`LIN`、`grasp` 序列
5. 生成新的 `.claude/tasks/task_<name>.json`
6. 如有必要，再建议用户用 `task_execute.py` 执行验证

## 如何利用视觉

当任务依赖当前场景，而用户没有提供精确坐标时，优先借助 `vision_realize`：

1. 用 `capture_and_realize.py` 询问场景里有哪些物体、它们的相对位置、谁在谁上面
2. 如果用户已经给出 bbox，或需要精确目标区域，调用 `SAM.py`
3. 如果需要抓取候选位姿，调用 `grasp_process.py`
4. 把视觉结果转成任务规划假设，并在生成 JSON 时写成稳定、可执行的动作序列

如果视觉结果仍不足以得到数值位姿，可以：

- 参考已有 task 文件中的落点坐标模式
- 使用用户已知的标准摆放位
- 明确说明这是基于当前示教样例的近似任务，不是在线闭环控制

## 动作编排规则

每次 pick-and-place 通常遵循这个模板：

1. `PTP` 到抓取点上方安全高度
2. `LIN` 沿 `tool_frame` 向下接近
3. `grasp --state 1` 闭合夹爪
4. `LIN` 沿 `tool_frame` 向上抬起
5. `PTP` 到放置点上方安全高度
6. `LIN` 向下接近放置
7. `grasp --state 0` 打开夹爪
8. `LIN` 向上撤离

推荐约定：

- 抓取前先确保夹爪打开
- 放置后撤离再进行下一步
- 多物体任务按依赖顺序生成，避免先放后挡住后续抓取
- 任务末尾优先补一个 `HOME`

## 生成要求

生成 task JSON 时要遵守：

- 文件名使用小写英文和下划线，例如 `task_stack_red_blue_on_green.json`
- 顶层 key 与文件名主体一致
- 保持 JSON 合法且便于直接执行
- 优先复用现有任务中的姿态约定：
  - `roll: 3.14`
  - `pitch: 0.0`
  - `yaw: -3.14`
- `LIN` 默认优先使用：
  - `"frame": "tool_frame"`
- 如果任务信息不足，不要伪造精确数值；应基于已有示教样例做合理近似，并向用户说明假设

## 输出要求

- 如果用户要“生成任务”，直接创建 `.claude/tasks/*.json`
- 回复中简洁说明任务文件路径
- 简要说明用了哪些视觉判断或坐标假设
- 如果缺少关键前提，直接指出缺口
- 不要输出冗长推理
