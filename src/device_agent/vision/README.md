# MuJoCo Camera Tools

这个目录放的是 MuJoCo 相机抓图相关的小工具。

当前提供的 CLI:

- [capture_camera.py](src/device_agent/vision/capture_camera.py)

## 功能

从 MuJoCo 发布到 ROS 的彩色图 topic 抓取一张图片并保存到文件，然后把图片和提示词一起发给千问模型。

默认 topic:

- `/table_overview/color/image_raw`

## 运行方式

这个工具依赖：

- `rclpy`
- `cv_bridge`
- `opencv-python`
- `openai`

并且要求 MuJoCo 的相机 topic 已经在发布。

还需要环境变量：

- `DASHSCOPE_API_KEY`

也可以直接写在：

- [mujoco_camera_tools/.env](src/device_agent/vision/.env)

## 常用示例

抓图并提问：

```bash
python3 src/mujoco_camera_tools/capture_camera.py "图中有什么物体？"
```

指定输出文件：

```bash
python3 src/mujoco_camera_tools/capture_camera.py \
  --output src/device_agent/vision/output/overview.png \
  "描述桌面上的红色方块位置"
```

指定 topic：

```bash
python3 src/mujoco_camera_tools/capture_camera.py \
  --topic /table_overview/color/image_raw \
  "夹爪和方块的相对位置是什么"
```

指定等待超时：

```bash
python3 src/mujoco_camera_tools/capture_camera.py \
  --timeout 10.0 \
  "图中描绘的是什么景象？"
```

指定模型：

```bash
python3 src/mujoco_camera_tools/capture_camera.py \
  --model qwen3.6-plus \
  "请输出一个简短的场景描述"
```

## 输出

默认输出路径：

- [table_overview.png](src/device_agent/vision/output/table_overview.png)

如果输出目录不存在，脚本会自动创建。

CLI 运行成功后会做两件事：

- 保存当前 topic 的一帧图片
- 在终端打印 Qwen 的回答

## `.env` 配置

工具会自动读取：

- [mujoco_camera_tools/.env](src/device_agent/vision/.env)

当前支持：

```env
DASHSCOPE_API_KEY=你的密钥
QWEN_MODEL=qwen3.6-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果系统环境变量已经设置了同名项，脚本会优先保留系统环境变量。
