---
name: vision-realize
description: 使用该技能来执行机器人视觉相关 CLI，包括从 MuJoCo 相机抓取 RGB 与深度图、调用多模态模型进行视觉理解、使用 SAM 基于 bbox 做分割，以及使用 GraspNet 基于当前输出结果执行抓取位姿推理。
---

# Vision Realize

该技能负责视觉，不负责机械臂运动控制。

适用场景：

- 抓取 MuJoCo 命名相机的一张图片
- 从 `/table_overview/color/image_raw` 获取当前实时彩色图
- 从 `/table_overview/depth/image_raw` 获取当前实时深度图
- 让模型基于当前相机图片回答“图中有什么物体”“夹爪和方块相对位置如何”“下一步该往哪个方向移动”
- 对图中一个或多个 bbox 调用 SAM 分割目标物体
- 基于当前 RGB、深度图和 SAM 掩码调用 GraspNet 做抓取推理

如果用户只是要规划机械臂、执行 PTP 或 LIN、控制夹爪，优先使用 `robot_control` skill。

## 相关文件

- Vision QA CLI: `/home/lx/smart_factory/src/device_agent/vision/capture_and_realize.py`
- SAM CLI: `/home/lx/smart_factory/src/device_agent/vision/SAM.py`
- GraspNet CLI: `/home/lx/smart_factory/src/device_agent/vision/grasp_process.py`

## 常用命令

抓图并让多模态模型回答一个问题：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/capture_and_realize.py "图中有什么物体？"
```

抓图并输出相对位置判断：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/capture_and_realize.py "夹爪和方块的相对位置是什么？请简短回答。"
```

抓图并要求结构化结果：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/capture_and_realize.py "请输出 JSON，字段包含 objects、cube_relative_to_gripper、scene_summary"
```

对单个 bbox 执行 SAM 分割：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/SAM.py --bbox 109 166 170 236
```

对多个 bbox 执行 SAM 分割：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/SAM.py \
  --bbox 109 166 170 236 \
  --bbox 296 167 354 236 \
  --bbox 471 167 529 236 \
  --bbox 242 22 402 87
```

基于当前输出目录中的彩色图、深度图和 SAM 掩码执行 GraspNet 抓取推理：

```bash
/home/lx/smart_factory/src/device_agent/.venv/bin/python /home/lx/smart_factory/src/device_agent/vision/grasp_process.py
```

## 工作方式

推荐按下面顺序组织视觉流程：

1. 先运行 `capture_and_realize.py` 获取当前 RGB 图、深度图和基础语义判断
2. 如果用户已经给出目标 bbox，运行 `SAM.py` 生成 `sam_result/masks_binary.png`
3. 如果用户要抓取位姿，再运行 `grasp_process.py`

### capture_and_realize.py 要点

- 需要使用虚拟环境解释器：`/home/lx/smart_factory/src/device_agent/.venv/bin/python`
- 位置参数是提示词，不能省略
- 会保存彩色图、深度 PNG、彩色深度可视化和深度 `.npy`
- 默认输出目录在 `/home/lx/smart_factory/src/device_agent/vision/output`

### SAM.py 要点

- 只接受重复的 `--bbox X1 Y1 X2 Y2`
- 可以重复传多个 `--bbox`
- 当前脚本不接收 `label`
- 主要输出：
  - `/home/lx/smart_factory/src/device_agent/vision/output/sam_result/bboxes_overlay.png`
  - `/home/lx/smart_factory/src/device_agent/vision/output/sam_result/masks_overlay.png`
  - `/home/lx/smart_factory/src/device_agent/vision/output/sam_result/masks_binary.png`

### grasp_process.py 要点

- 默认读取以下文件，不需要额外传参：
  - `/home/lx/smart_factory/src/device_agent/vision/output/table_overview.png`
  - `/home/lx/smart_factory/src/device_agent/vision/output/table_overview_depth.png`
  - `/home/lx/smart_factory/src/device_agent/vision/output/sam_result/masks_binary.png`
- 因此通常需要先完成抓图和 SAM 分割
- 该脚本会弹出 Open3D 可视化窗口

## 提示词建议

- 场景描述：
  `图中描绘的是什么景象？`
- 物体识别：
  `图中有什么物体？`
- 相对位置：
  `夹爪和方块的相对位置是什么？`
- 抓取微调建议：
  `如果要抓取红色方块，末端更应该沿x、y还是z方向微调？`
- 结构化结果：
  `请输出 JSON，字段包含 objects、cube_relative_to_gripper、scene_summary`

## 输出要求

- 对用户简洁说明你正在执行的命令
- 如果命令失败，直接返回失败原因
- 如果只是要命令，直接给命令
- 不要展开冗长推理
