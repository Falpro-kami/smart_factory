---
name: production
description: 使用 split_mcp_server 的 split_product_order 完成生产订单创建、拆单、校验和写入工单；用户明确下发订单时再使用 submit_order_to_scheduler 投入调度。
---

# 生产订单入口

用于智能产线演示中的生产订单处理。新建订单和拆单时调用 `split_product_order`；用户明确要求下发订单、投入调度或开始执行时，再调用 `submit_order_to_scheduler`。

## 固定流程

`split_product_order` 封装完整业务链路：

1. 根据 `order_id`、`product_id` 或 `product_name` 创建或更新实时订单。
2. 从 Neo4j 查询产品、工艺路线、输入/输出物料、可执行设备。
3. 从 MySQL 查询库存、设备、订单和已有工单。
4. 接收智能体生成的 `work_order_draft`，或在未提供草案时生成规则基准草案。
5. 校验层核对工序链完整性、设备存在性、物料数量、前后置关系，并补全工单 ID、状态、时间、AGV 运输和物料明细。
6. 将完整工单写入 MySQL `order.work_orders`。
7. 保持订单和工单在已计划状态，不自动投入后台调度队列。
8. 只有用户明确要求下发订单时，调用 `submit_order_to_scheduler` 将订单投入后台调度队列。

## 必要参数

- `order_id`：订单编号；可缺省，后端按 `PO-YYYYMMDD-序号` 自动生成。
- `product_id` 或 `product_name`：至少提供一个。
- `quantity`：订单内产品件数。大于 1 时应在 `work_order_draft.items` 中拆为同等数量的单件产品链；未提供草案时校验层会自动生成。
- `work_order_draft`：可选，智能体生成的工单草案。推荐结构为 `order + items[].work_orders[]`。
- `material_ids` 或 `materials`：可选，用于指定本次出库物料；未指定时按库存自动分配。
- `pallet_id`、`agv_id`：可选。

## 草案要求

- 顶层包含 `order`：`order_id`、`product_id`、`product_name`、`quantity`。
- `items` 表示单件产品，`item_id` 使用 `{order_id}-ITEM-001` 格式。
- 每个 item 内的 `work_orders` 至少包含：`sequence`、`工单类型`、`工序编号`、`分配设备`、`description`。
- 工单名称使用“产品名称 + 工单类型”，例如 `立方堆出库`、`立方堆堆积`。
- 普通工单的起始工站和目标工站等于分配设备；运输工单可不生成，由校验层按相邻设备变化自动插入。
- MySQL 工单表使用 `分配设备` 字段，不使用旧的 `分配工站`。
- MySQL 订单和工单表不保存生产数量字段，多个产品通过多个 `item` 区分。

## 输出

向用户简要说明订单是否创建、工单数、item 数，并说明订单尚未下发。不要展示完整 SQL、Cypher 或数据库连接细节。
