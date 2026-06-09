# split_mcp_server 逻辑说明

`split_mcp_server` 是一个基于 MCP stdio 的低层服务，向外暴露 `split_product_order` 工具，用于把产品订单拆分为生产工单。

## 工具信息

- 服务名：`split_mcp_server`
- 工具名：`split_product_order`
- 入口文件：`src/split_mcp_server/server.py`
- 启动入口：`src/split_mcp_server/__main__.py`
- 运行方式：通过 MCP stdio 与客户端通信

## 输入参数

`split_product_order` 接收一个 JSON 对象：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `order_id` / `orderId` | string | 是 | 产品订单编号，用于生成工单编号 |
| `product_id` / `productId` | string | 否 | Neo4j 中 `Product.productId` |
| `product_name` / `productName` | string | 否 | Neo4j 中 `Product.name`，支持名称包含匹配 |
| `quantity` | integer | 否 | 订单数量，默认值为 `1` |
| `pallet_id` / `palletId` | string | 否 | 物料盘编号，默认 `{order_id}-PALLET` |
| `agv_id` / `agvId` | string | 否 | AGV 小车编号，默认 `AGV-001` |

约束：

- `order_id` 不能为空。
- `product_id` 和 `product_name` 至少提供一个。
- `quantity` 必须大于 `0`。

## 环境变量

服务通过 `.env` 或系统环境变量读取 Neo4j 连接配置：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NEO4J_URI` | `bolt://127.0.0.1:7687` | Neo4j Bolt 地址 |
| `NEO4J_USERNAME` | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | 空字符串 | Neo4j 密码 |
| `NEO4J_DATABASE` | `neo4j` | Neo4j 数据库名 |

`.env` 的读取路径为 `SIMENS_Agent_Demo/.env`。

## 核心流程

1. 读取并规范化入参。
2. 连接 Neo4j。
3. 查询产品节点：
   - 节点标签需包含 `Product`，大小写不敏感。
   - 如果提供 `product_id`，按 `Product.productId` 精确匹配。
   - 如果提供 `product_name`，按 `Product.name` 包含匹配，大小写不敏感。
4. 未找到产品时，返回 `success: false`，不生成工单。
5. 找到产品后，查询产品相关部件：
   - 从产品节点出发，沿 1 到 3 跳有向关系查找标签为 `Part` 的节点。
   - 结果按 `order`、`partId`、`name`、`type` 排序。
6. 查询工艺路线：
   - 优先读取产品直接关联的 `ProcessInstance` 步骤：
     - 关系类型为 `HAS_STEP`，大小写不敏感。
     - 根据 `process_name` 关联 `Process` 节点。
     - 读取步骤的 `USES` 输入物料和 `PRODUCES` 输出物料。
   - 如果没有 `ProcessInstance` 路线，则查找产品 1 到 4 跳范围内关联的 `AssemblyStep`。
   - 如果仍未找到，则退化为读取数据库中所有 `AssemblyStep`。
7. 按“出库 -> 加工 -> 质检 -> 入库”生成工单。
8. 当相邻加工工单的执行设备不同，自动插入 `AGV运输` 工单。
9. 返回拆分结果和工单列表。

## 工单生成规则

每个工单由 `make_work_order` 生成，基础字段如下：

| 字段 | 说明 |
| --- | --- |
| `work_order_id` | 工单编号，格式为 `{order_id}-WO-{sequence:03d}` |
| `source_order_id` | 来源订单编号 |
| `sequence` | 工单序号，从 `1` 开始递增 |
| `stage` | 工单阶段 |
| `title` | 工单标题 |
| `content` | 工单内容 |
| `product_id` | 产品 ID |
| `product_name` | 产品名称 |
| `quantity` | 订单数量 |
| `status` | 初始状态，固定为 `pending` |
| `created_at` | 创建时间，精确到秒 |
| `route_step` | 仅加工工单包含，对应 Neo4j 工艺步骤数据 |
| `assigned_device` | 加工工单可包含，对应工序执行设备 |
| `previous_step` / `next_step` | 加工工单可包含，对应前置和后置工序 |

固定工单的 `process_id` / `工序编号` 使用确定值：

| 工单类型 | 工序编号 |
| --- | --- |
| 出库 | `OUTPUT-001` |
| 质检 | `DETECT-001` |
| 入库 | `INPUT-001` |
| 贴标 | `LABEL-001` |

生成顺序：

1. 出库工单
   - 固定生成 1 条。
   - 内容基于产品 BOM 部件摘要。
   - 部件摘要最多展示前 12 个部件，超过后追加总数提示。

2. 加工工单
   - 根据查询到的工艺步骤逐条生成。
   - 每个步骤生成 1 条加工工单。
   - 工单标题包含步骤编号和工序名称。
   - 工单内容包含工艺说明、输入物料、输出物料。
   - 将完整步骤数据写入 `route_step`。
   - 若工艺步骤含设备字段，会写入 `assigned_device`。
   - 写入前置工序 `previous_step` 和后置工序 `next_step`。

3. AGV运输工单
   - 仅当上一条有执行设备的加工工单与当前加工工单执行设备不同才生成。
   - 阶段固定为 `AGV运输`，`task_type` 固定为 `agv_transport`。
   - `transport_task` 包含 AGV 编号、物料盘编号、前后工单、起点设备、目标设备和触发条件。

4. 质检工单
   - 固定生成 1 条。
   - 用于产品完工后的质量检查。

5. 入库工单
   - 固定生成 1 条。
   - 用于质检合格后的成品入库。

## 返回结构

成功时返回：

```json
{
  "success": true,
  "message": "...",
  "order_id": "...",
  "product": {},
  "quantity": 1,
  "agv_id": "AGV-001",
  "pallet_id": "...",
  "route_step_count": 0,
  "agv_transport_count": 0,
  "work_order_count": 0,
  "work_orders": []
}
```

未找到产品时返回：

```json
{
  "success": false,
  "message": "...",
  "order_id": "...",
  "product_id": "...",
  "product_name": "...",
  "work_orders": []
}
```

## 关键函数

| 函数 | 作用 |
| --- | --- |
| `load_env` | 从 `.env` 加载环境变量 |
| `get_neo4j_driver` | 创建 Neo4j Driver |
| `clean_value` | 将 Neo4j 返回值清洗为 JSON 可序列化类型 |
| `normalize_props` | 规范化节点属性字典 |
| `find_product` | 根据产品 ID 或名称查询产品节点 |
| `find_product_parts` | 查询产品关联的 BOM 部件 |
| `find_route_steps` | 查询产品工艺路线 |
| `extract_assigned_device` | 从工艺步骤中提取执行设备信息 |
| `device_changed` | 判断相邻加工工单执行设备是否变化 |
| `make_work_order` | 生成单条工单对象 |
| `make_agv_transport_order` | 生成 AGV 运输工单对象 |
| `split_order` | 拆分订单的主逻辑 |
| `list_tools` | 向 MCP 客户端声明工具 schema |
| `call_tool` | 接收 MCP 工具调用并返回 JSON 文本 |

## 注意事项

- 当前逻辑只生成工单数据并返回给调用方，不写回 Neo4j 或其他数据库。
- 工艺路线查询存在三级兜底：`ProcessInstance`、产品关联 `AssemblyStep`、全库 `AssemblyStep`。
- 如果 Neo4j 中没有任何可用工艺步骤，仍会生成出库、质检、入库 3 类固定工单。
- 源文件中部分中文字符串可能存在编码显示异常，但不影响对业务流程和数据结构的判断。
