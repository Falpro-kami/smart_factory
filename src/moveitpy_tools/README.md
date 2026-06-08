# MoveItPy Quick Guide

这份说明配套 [test.py](/home/lx/dev_ws/src/moveitpy_tools/test.py) 使用，目标是让你能尽快上手 `moveit_py` 做规划测试。

脚本现在会直接从你工程里的：

- [ur5e_2f85.srdf](/home/lx/dev_ws/src/ur5e_2f85_moveit_config/config/ur5e_2f85.srdf)
- [kinematics.yaml](/home/lx/dev_ws/src/ur5e_2f85_moveit_config/config/kinematics.yaml)
- [joint_limits.yaml](/home/lx/dev_ws/src/ur5e_2f85_moveit_config/config/joint_limits.yaml)
- [ompl_planning.yaml](/home/lx/dev_ws/src/ur5e_2f85_moveit_config/config/ompl_planning.yaml)
- [ur5e_2f85.urdf.xacro](/home/lx/dev_ws/src/ur10e_2f85_mujoco/description/urdf/ur5e_2f85.urdf.xacro)

读取配置，生成一份临时 ROS 参数文件，再交给 `MoveItPy` 加载。这样比“完全依赖参数服务器”更稳，也更贴近 `moveit_py` 在 Jazzy 里的原生初始化方式。对 Jazzy 来说，`planning_pipelines` 还需要按嵌套结构提供：

```yaml
planning_pipelines:
  pipeline_names: [ompl]
  namespace: ""
```

## 1. 先决条件

运行脚本之前，先启动 MoveIt:

```bash
cd /home/lx/dev_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch ur5e_2f85_moveit_config demo.launch.py
```

然后另开一个终端运行脚本:

```bash
cd /home/lx/dev_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 src/moveitpy_tools/test.py
```

如果你想避免每次都重建一遍 `MoveItPy`，推荐直接用交互模式:

```bash
python3 src/moveitpy_tools/test.py --interactive
```

如果你想要“单次调用外观，但内部仍然复用同一个 MoveItPy”，推荐用：

```bash
python3 src/moveitpy_tools/moveitpy_server.py
python3 src/moveitpy_tools/moveitpy_cli.py HOME
python3 src/moveitpy_tools/moveitpy_cli.py LIN --dz -0.10
python3 src/moveitpy_tools/moveitpy_cli.py execute_last
```

## 2. 最常用对象

### `MoveItPy`

主入口对象。常用能力:

- 创建规划接口
- 获取机器人模型
- 执行规划结果

典型写法:

```python
from moveit.planning import MoveItPy
from moveit.utils import create_params_file_from_dict

params_file = create_params_file_from_dict(config_dict, "moveit_py_test")
moveit_py = MoveItPy(
    node_name="moveit_py_test",
    launch_params_filepaths=[params_file],
)
```

常用方法:

- `get_planning_component(group_name)`
- `get_robot_model()`
- `execute(robot_trajectory, controllers=[])`
- `shutdown()`

### `PlanningComponent`

某个规划组的规划入口，比如 `arm` 或 `gripper`。

典型写法:

```python
planning_component = moveit_py.get_planning_component("arm")
```

常用方法:

- `set_start_state_to_current_state()`
- `set_goal_state(...)`
- `plan()`
- `set_workspace(...)`
- `set_path_constraints(...)`

## 3. 常见目标

### 命名目标

适合回到 `home` 这类 SRDF 里已有的姿态。

```python
planning_component.set_goal_state(configuration_name="home")
```

运行:

```bash
python3 src/moveitpy_tools/test.py --goal home
```

### 位姿目标

适合让 `tool_frame` 去一个目标点。

```python
pose_goal.header.frame_id = "world_frame"
planning_component.set_goal_state(
    pose_stamped_msg=pose_goal,
    pose_link="tool_frame",
)
```

运行:

```bash
python3 src/moveitpy_tools/test.py --goal pose --x 0.15 --y 0.45 --z 1.0
```

## 4. 规划和执行

### 只规划

```python
plan_result = planning_component.plan()
```

判断结果:

```python
if not plan_result:
    print("Planning failed.")
```

### 规划后执行

```python
moveit_py.execute(plan_result.trajectory, controllers=[])
```

运行:

```bash
python3 src/moveitpy_tools/test.py --goal home --execute
```

### 笛卡尔直线规划

`moveitpy_tools` 现在还支持一个专门的 CLI 命令，用来做末端直线规划：

```bash
python3 src/moveitpy_tools/moveitpy_cli.py LIN --dz -0.10
```

这条命令会：

- 以当前 `tool_frame` 为起点
- 保持当前末端姿态不变
- 默认在 `world_frame` 下做相对位移，也可以用 `--frame tool_frame` 切到工具坐标系
- 调用 MoveIt 的 `compute_cartesian_path` 服务生成直线路径

常见例子：

```bash
python3 src/moveitpy_tools/moveitpy_cli.py LIN --dz -0.05
python3 src/moveitpy_tools/moveitpy_cli.py execute_last
```

沿工具坐标系移动:

```bash
python3 src/moveitpy_tools/moveitpy_cli.py LIN --frame tool_frame --dz -0.05
python3 src/moveitpy_tools/moveitpy_cli.py execute_last
```

横向微调：

```bash
python3 src/moveitpy_tools/moveitpy_cli.py LIN --dx 0.03 --dy -0.02
python3 src/moveitpy_tools/moveitpy_cli.py execute_last
```

常用参数：

- `--dx --dy --dz`：相对当前末端的直线位移，单位米
- `--frame`：位移使用的坐标系，可选 `world_frame` 或 `tool_frame`，默认 `world_frame`
- `--max-step`：笛卡尔插值步长，默认 `0.01`

这类路径仍然会做碰撞检测，所以如果中途碰桌子、碰方块、不可达，规划会失败或者只得到部分路径。

### 交互模式

交互模式只初始化一次 `MoveItPy`，适合连续测试多个目标:

```bash
python3 src/moveitpy_tools/test.py --interactive
```

启动后可用命令:

```text
home
pose 0.15 0.45 1.0
execute
quit
```

推荐流程:

```text
home
execute
pose 0.15 0.45 1.0
execute
```

## 5. 常见接口怎么用

### `set_start_state_to_current_state()`

把当前机器人真实状态当作规划起点。大多数测试都应该先调这个。

### `set_goal_state(configuration_name="home")`

用 SRDF 里已有的命名状态做目标。

### `set_goal_state(pose_stamped_msg=..., pose_link="tool_frame")`

用位姿约束做目标，适合末端到达测试。

### `plan()`

返回规划结果对象。常用的是其中的:

- `trajectory`

### `execute(...)`

把 `plan().trajectory` 发给执行器。

## 6. 你这套工程里建议优先怎么用

先从这两个命令开始:

```bash
python3 src/moveitpy_tools/test.py --goal home
python3 src/moveitpy_tools/test.py --goal pose --x 0.15 --y 0.45 --z 1.0
```

调通后再加执行:

```bash
python3 src/moveitpy_tools/test.py --goal home --execute
```

如果你要频繁反复试，优先用:

```bash
python3 src/moveitpy_tools/test.py --interactive
```

## 7. 常见坑

- `demo.launch.py` 没启动时，`MoveItPy` 会等不到 `robot_description` 或规划服务。
- 如果你改了 xacro / SRDF / OMPL 配置，`test.py` 会直接读源码目录里的最新版本，再生成临时参数文件。
- 位姿目标如果失败，优先检查:
  - `frame_id` 是否正确
  - `pose_link` 是否是 `tool_frame`
  - 目标是否在机械臂工作空间内
- 如果环境里桌子和方块参与碰撞，规划会比纯机械臂更难，先用 `arm` 组最稳。

## 8. 后面可以继续扩展什么

你后面最值得继续补的通常是：

- 读取当前末端位姿
- 添加/移除碰撞物体
- attach/detach 物体
- 夹爪单独控制
- Pick and Place 流程

如果你愿意，下一步我可以继续把 `test.py` 扩成：

- 一个 `attach cube` 示例
- 一个 `gripper open/close` 示例
- 一个完整的抓取测试模板
