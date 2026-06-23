# split_mcp_server 逻辑说明

`split_mcp_server` 是一个基于 MCP stdio 的低层服务。业务顺序是先创建订单，再基于订单拆分工单。

## 工具

- `create_production_order`：创建生产订单，只写入 `order.orders`。
- `validate_work_order_plan`：基于已创建订单校验并补全生产智能体生成的 WorkOrderPlan。
- `persist_work_order_plan`：校验通过后将工单写入 `order.work_orders`，并将订单推进到已计划。
- `submit_order_to_scheduler`：用户明确要求下发订单、投入调度或开始执行时，将订单投入调度队列。

## 主流程

1. 生产智能体理解用户需求，确定产品和数量。
2. 调用 `create_production_order` 创建订单。
3. 生产智能体查询 Neo4j / MySQL，生成 WorkOrderPlan。
4. 调用 `persist_work_order_plan` 完成校验、补全和工单落库。
5. 用户明确要求开始执行时，调用 `submit_order_to_scheduler`。

## validate_work_order_plan 输入

工具接收 `plan` 对象，也可以直接接收 WorkOrderPlan 本体。`order.order_id` 对应的订单必须已经通过 `create_production_order` 创建。

WorkOrderPlan 顶层结构：

```json
{
  "order": {},
  "items": []
}
```

`order` 必填字段：

| 字段 | 说明 |
| --- | --- |
| `order_id` | 订单编号 |
| `product_id` | Neo4j 产品 ID |
| `product_name` | 产品名称 |
| `quantity` | 订单内产品件数 |

`items` 要求：

- `items` 数量必须等于 `order.quantity`。
- 每个 item 必须包含 `item_no`。
- `item_id` 由校验层生成，格式为 `{order_id}-ITEM-{item_no:03d}`。

每张工单必填字段：

| 字段 | 说明 |
| --- | --- |
| `sequence` | 从 1 开始连续 |
| `工单类型` | 出库、加工、质检、贴标、入库、运输 |
| `工序编号` | 对应工序 ID |
| `工单名称` | 工单名称 |
| `分配设备` | 执行设备 |
| `起始设备` | 起始设备 |
| `目标设备` | 目标设备 |
| `description` | 工单说明 |
| `input_materials` | 输入物料大类和数量 |
| `output_materials` | 输出物料大类和数量 |

## 校验内容

- 校验 `order_id`、`product_id`、`product_name`、`quantity`。
- 校验 `order_id` 对应订单已经存在。
- 校验 `items` 数量和 `item_no`。
- 校验工单 `sequence` 连续性。
- 校验工单类型、工序编号、设备和 AGV 运输链路。
- 从 Neo4j 读取产品工艺路线、`uses` / `produces` 物料关系，校验路线和物料大类/数量。
- 补齐工单 ID、前置工单、后续工单、状态、创建时间、更新时间。

## 输出

校验通过时返回 `normalized_plan`，其中包含可落库的订单、items 和工单列表。物料实例分配当前保留框架：`allocation_status=pending`、`material_instances=[]`。
