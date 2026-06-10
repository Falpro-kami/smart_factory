---
name: robot-control
description: 使用该技能来通过 moveitpy_cli 调用 MoveItPy 常驻服务，执行机械臂规划、执行、位姿目标、笛卡尔直线规划、查询末端位姿，以及夹爪开合控制。
---

# Robot Control

该技能只负责机器人控制，不负责视觉。

适用场景：

- 通过命令行快速规划到 `home`
- 规划一个末端位姿目标
- 记录当前末端位姿为 PTP 工步 JSON
- 规划一个笛卡尔直线路径
- 查询当前末端 `tool_frame` 位姿
- 打开或闭合夹爪
- 执行上一次规划结果
- 调整规划时间

如果用户要抓图、看图问答、SAM 分割或 GraspNet 抓取推理，优先使用 `vision_realize` skill。

## 相关文件

- CLI: `/home/lx/smart_factory/src/device_agent/moveitpy_tools/moveitpy_cli.py`

## 常用命令

规划到 `home`：

```bash
python3 moveitpy_tools/moveitpy_cli.py HOME
```

PTP 运动到自定义位姿目标：

```bash
python3 moveitpy_tools/moveitpy_cli.py PTP --x 0.15 --y 0.45 --z 1.0 --roll 0.0 --pitch 1.57 --yaw 0.0
```

记录当前末端位姿为 PTP 工步：

```bash
python3 moveitpy_tools/moveitpy_cli.py PTP_record --pretty
```

LIN 笛卡尔直线路径(基于世界坐标的绝对位移)：

```bash
python3 moveitpy_tools/moveitpy_cli.py LIN --frame world_frame --x 0.05 --y 0.05 --z -0.05
```

LIN 笛卡尔直线路径(基于世界坐标的相对位移)：

```bash
python3 moveitpy_tools/moveitpy_cli.py LIN --frame world_frame --dx 0.05 --dy 0.05 --dz -0.05
```

LIN 笛卡尔直线路径(基于工具坐标的相对位移)：

```bash
python3 moveitpy_tools/moveitpy_cli.py LIN --frame tool_frame --dx 0.05 --dy 0.05 --dz -0.05
```

调整规划时间：

```bash
python3 moveitpy_tools/moveitpy_cli.py set_planning_time --seconds 1.5
```

查询当前末端位姿：

```bash
python3 moveitpy_tools/moveitpy_cli.py get_tool_pose
```

闭合夹爪：

```bash
python3 moveitpy_tools/moveitpy_cli.py grasp --state 1
```

打开夹爪：

```bash
python3 moveitpy_tools/moveitpy_cli.py grasp --state 0
```

## 工作方式

执行任务时，优先遵循以下流程：

1. 根据用户目标选择 `HOME`、`PTP` 或 `LIN`
2. 如果用户要求更快或更稳，可先调用 `set_planning_time`

`LIN` 的语义是：

- 以当前 `tool_frame` 为起点
- 保持当前末端姿态不变
- 在 `world_frame` 下做相对直线位移
- 常用于末端竖直下压、抬升、横向微调

## 输出要求

- 对用户简洁说明你正在执行的命令
- 如果命令失败，直接返回失败原因
- 不要展开冗长推理
