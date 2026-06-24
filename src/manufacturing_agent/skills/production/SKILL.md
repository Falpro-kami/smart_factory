---
name: production
description: 使用 split_mcp_server 先创建生产订单，再基于已创建订单校验、补全并落库 WorkOrderPlan；用户明确下发订单时再使用 submit_order_to_scheduler 投入调度。
---

# 生产订单入口

创建订单时调用 `create_production_order`。拆分工单时基于已创建订单调用 `persist_work_order_plan`；只需要预检时调用 `validate_work_order_plan`。

## 固定流程

1. 查询 Neo4j 产品基础信息，确定 `product_id`、`product_name`、`quantity`。
2. 调用 `create_production_order` 创建订单，并将 `quantity` 写入 MySQL `order.orders`.`生产数量`。
3. 查询 Neo4j 工艺路线、输入/输出物料和可执行设备。
4. 查询 MySQL 设备、订单和已有工单。
5. 基于已创建订单生成 `WorkOrderPlan` JSON。
6. 调用 `persist_work_order_plan` 校验、补全并写入工单。
7. 用户明确要求下发订单、投入调度或开始执行时，再调用 `submit_order_to_scheduler`。

## WorkOrderPlan 要求

- 顶层包含 `order`：`order_id`、`product_id`、`product_name`、`quantity`。
- 顶层包含 `items`。
- 每个 item 包含 `item_no` 和 `work_orders`。
- 每张工单包含 `sequence`、`工单类型`、`工序编号`、`工单名称`、`分配设备`、`起始设备`、`目标设备`、`description`。
- 每张工单包含 `input_materials` 和 `output_materials`，物料项使用 `material_type` 和 `quantity`。

## 输出

拆分工单并调用 `persist_work_order_plan` 落库后，最终回复必须打印完整 WorkOrderPlan JSON。

输出规则：

- 优先打印 `persist_work_order_plan` 返回结果中的 `validation.normalized_plan`。
- 如果校验失败，打印 `validation.draft_normalized_plan`，并简要说明失败原因。
- 不要只输出校验摘要、工单数或 item 数。
- 不要展示完整 SQL、Cypher 或数据库连接细节。
- 除非用户要求说明过程，否则最终回复只输出 JSON 对象，不添加 Markdown 代码块或额外解释。
