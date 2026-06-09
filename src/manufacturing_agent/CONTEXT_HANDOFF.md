# CONTEXT_HANDOFF

## 项目现状

- 当前项目根目录：`E:\codenew\SIMENS_Agent_Demo`
- 旧嵌套目录：`E:\codenew\mujoko_ur5e` 已删除。
- 前端：`digital-twin-frontend`
- 后端：`agent_backend_adapter`
- 拆单、调度、RocketMQ 消费：`split_mcp_server`
- 本地技能：`skills`
- 一键启动：`start_system.ps1`
- 一键停止：`stop_system.ps1`

## 当前目标

项目现在聚焦智能产线数字孪生演示，不再维护机械臂/MuJoCo/UR10e 控制能力。核心链路是：

- 前端展示实时订单、设备、库存、成品库存和历史数据。
- 新订单拆单时从 Neo4j 查询产品、工艺和原料需求。
- 拆单工具从 MySQL `store.materials` 分配具体库存物料。
- 出库完成后删除已分配的 `store.materials` 行。
- 加工后执行贴标，生成成品标签编号。
- 入库完成后写入 MySQL `store.product`。
- 工单完成/失败后归档到 MySQL `Data.order_work_order_history`，并清理实时库 `order.orders`、`order.work_orders`。
- RocketMQ 用于工单下发和设备事件回传。

## 目录与上下文约定

- 本项目已移除 vexp 依赖，后续不需要 `run_pipeline`。
- 使用 `rg`、Git、本地文件和项目脚本定位问题即可。
- 不要读取或恢复 `.history`、`.runtime`、`__pycache__`、`rocketmq/store`、`rocketmq/logs`、长日志或大段 JSON。
- 新项目根目录下已清理 `.history`、`.runtime`、`rocketmq/store` 和 `__pycache__`。
- `.vscode/settings.json` 已排除上述缓存/运行时目录。
- `.gitignore` 已忽略 `.env`、`.history/`、`.runtime/`、`__pycache__/`、`*.pyc`、`*.log`、RocketMQ store/logs 等。

推荐搜索模板：

```powershell
rg -n "关键词" E:\codenew\SIMENS_Agent_Demo `
  -g "!**/.history/**" `
  -g "!**/.runtime/**" `
  -g "!**/__pycache__/**" `
  -g "!**/rocketmq/store/**" `
  -g "!**/rocketmq/logs/**" `
  -g "!**/uv.lock"
```

## 已完成的清理

- 已删除旧项目目录 `E:\codenew\mujoko_ur5e`。
- 已删除旧独立聊天前端 `agent-chat-frontend`。
- 已删除旧机械臂控制目录 `robotcontrol`。
- 已删除旧 UR10e/2F85 资产目录 `ur10e_2f85`。
- 已删除机械臂抓取 skill：`skills/grasp`。
- `agent_core.py` 不再加载 `robotcontrol` 或 UR10e LangChain 工具。
- 前端提示文案已移除 MuJoCo/UR10e/robotcontrol 相关描述。

## 关键工具能力

### `split_mcp_server/src/split_mcp_server/server.py`

- 固定工序编号：
  - 出库：`OUTPUT-001`
  - 质检：`DETECT-001`
  - 入库：`INPUT-001`
  - 贴标：`LABEL-001`
- 订单 ID 列兼容：
  - `订单编号`
  - `订单ID`
  - `order_id`
  - `orderId`
  - `id`
- `split_product_order` 已封装：
  - Neo4j 产品匹配。
  - Neo4j 产品部件/工艺路线读取。
  - MySQL `store.materials` 具体库存物料分配。
  - 出库、加工、贴标、质检、入库工单生成。
  - 相邻工站变化时插入 AGV 运输工单。
  - 加工工站从 MySQL `device.workstation` 分配。
  - 出库工单写入 `material_ids`、`required_materials`、`allocated_materials` 和 `description`。
  - 贴标/入库工单写入成品标签编号。
- 正常生产调度优先使用 `WorkOrderScheduler`。
- `WorkOrderDelivery` 是底层直发工具，常规流程不优先使用。

### `split_mcp_server/src/split_mcp_server/device_event_consumer.py`

- 消费 `DeviceEventReport`。
- 出库工单完成后，从 `description` 提取物料编号并删除 `store.materials` 对应行。
- 入库工单完成后，从 `description` 提取成品标签编号并写入/更新 `store.product`。
- 工单完成/失败后更新订单状态。
- 订单完成/失败后归档到 `Data.order_work_order_history` 并清理实时表。
- 启动消费者时会扫描并清理已归档实时订单残留。

### `agent_backend_adapter`

- `/api/digital-twin/store` 返回 `store.materials` 和 `store.product`。
- Ontology 实时订单 catalog 只读取实时表。
- 排除 `backup`、`history`、`archive`、`scheduler`、`queue` 等非实时表，避免已归档订单回到实时 Orders。

### `digital-twin-frontend`

- 当前主界面入口：
  - `digital-twin-frontend/index.html`
  - `digital-twin-frontend/app.mjs`
  - `digital-twin-frontend/styles.css`
- 前端端口固定为 `5175`。
- 项目提供 `digital-twin-frontend/serve.py` 作为无缓存静态服务，避免浏览器缓存旧 `app.mjs`。

## 当前注意事项

- 真实 MySQL `order.orders` 表当前订单 ID 列是 `订单ID`，不是 `订单编号`，代码已有兼容。
- `store.materials` 是“每行一个物料件/批次”，没有数量字段；出库扣减通过删除已分配物料行实现。
- 不要对真实 `store.materials` 随意模拟完成事件，因为会真实删除库存行。
- 如果要测试库存扣减，先插入测试物料或使用测试订单。
- `store.product` 已创建，只有入库工单完成事件触发后才写入成品。
- RocketMQ 设备互联时优先使用以太网 `192.168.1.10`；如使用真实设备，需确认该 IP 存在并放行 TCP `9876`、`10909-10912`。

## 已验证过的命令

```powershell
python -m py_compile split_mcp_server\src\split_mcp_server\server.py split_mcp_server\src\split_mcp_server\device_event_consumer.py
python -m py_compile agent_backend_adapter\ontology_api.py agent_backend_adapter\app.py
node --check digital-twin-frontend\app.mjs
```

迁移到 `E:\codenew\SIMENS_Agent_Demo` 后已验证：

```powershell
python -m py_compile agent_core.py main.py agent_backend_adapter\app.py
node --check digital-twin-frontend\app.mjs
```

## 下一步建议

1. 整合 `skills/order`、`skills/plan`、`skills/assignment` 为单个 `production` skill。
2. 新增或完善一个硬编码生产入口工具，例如 `create_production_order`：
   - 创建订单。
   - 调用 `split_product_order`。
   - 写入 `order.work_orders`。
   - 提交 `WorkOrderScheduler`。
3. 用测试订单完整跑一遍：
   - 新建订单。
   - 拆单。
   - 提交调度。
   - 模拟出库完成事件。
   - 验证 `store.materials` 删除对应物料。
   - 模拟入库完成事件。
   - 验证 `store.product` 新增成品。
4. 如果新会话继续，先读取本文件，不要重复读取长日志、`.history` 或运行时目录。
