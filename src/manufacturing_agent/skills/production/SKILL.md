---
name: production
description: 使用 split_mcp_server 的 split_product_order 完成生产订单创建、拆单、写入工单和提交调度。
---

# 生产订单入口

用于智能产线演示中的生产订单处理。遇到新建订单、拆单、排产、工单分配、提交调度等需求时，只调用 `split_product_order`。

## 固定流程

`split_product_order` 已固定封装完整业务链路：

1. 根据 `order_id`、`product_id` 或 `product_name`、`quantity` 创建或更新实时订单。
2. 从 Neo4j 查询产品、BOM、工艺路线。
3. 从 MySQL `store.materials` 分配本次出库的具体库存物料。
4. 按出库、加工、贴标、质检、入库生成工单。
5. 相邻工站变化时自动插入 AGV 运输工单。
6. 将工单写入 MySQL `order.work_orders`。
7. 将订单提交到后台调度队列，由常驻调度服务下发工单。

## 工具约束

- 不再分别使用旧的 `order`、`plan`、`assignment` 技能。
- 不新增订单、计划、分配类工具。
- 常规生产流程只调用 `split_product_order`。
- 不直接模拟出库或入库完成事件；真实完成事件会触发库存删除和成品入库。

## 必要参数

- `order_id`：订单编号。
- `product_id` 或 `product_name`：至少提供一个。
- `quantity`：生产数量，默认 1。
- `material_ids` 或 `materials`：可选；用于指定本次出库物料。
- `pallet_id`、`agv_id`：可选。

## 输出

向用户简要说明订单是否创建、工单数、是否提交调度。不要展示完整 SQL、Cypher 或数据库连接细节。
