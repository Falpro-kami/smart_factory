---
name: work-order-plan
description: 生成生产订单 WorkOrderPlan JSON。用于把产品工艺路线、设备分配和物料需求组织成严格字段格式的工单计划 JSON。
---

# WorkOrderPlan JSON

只输出一个 JSON 对象，不输出解释文字、Markdown、代码块或注释。

生成完成后，必须把完整 WorkOrderPlan JSON 打印在最终回复中。不要只保存到文件、不要只传给工具、不要省略 JSON 内容。

## 生成前先一次性查询

在生成 JSON 前，先一次性查清以下信息，再一次性生成完整 JSON。

### 产品和工艺路线

从 Neo4j 查询产品、工序路线、工序类型、输入物料、输出物料。

查询对象：

```text
product
process
material
product -[:has_step]-> process
process -[:uses]-> material
process -[:produces]-> material
```

需要取得：

```text
product.product_id
product.name
process.process_id
process.name
process.description
process.process_type
process.stepId 或 order
uses 关系上的 quantity
produces 关系上的 quantity
material.name 或 material.type
```

按 `process.stepId` 或 `process.order` 排序生成工艺路线。

物料名称优先使用 `material.name`；只有 `material.name` 为空时才使用 `material.type`。

使用下面这种查询方式获取产品工艺路线。先在 `WITH` 中计算排序字段，再 `ORDER BY`，最后再聚合；不要在 `RETURN collect(...)` 后直接 `ORDER BY hs.order`。

```cypher
MATCH (p:product)
WHERE ($product_id <> '' AND p.product_id = $product_id)
   OR ($product_name <> '' AND p.name = $product_name)
MATCH (p)-[hs:has_step]->(proc:process)
OPTIONAL MATCH (proc)-[cr:CAN_RUN_ON]-(dev:device)
OPTIONAL MATCH (proc)-[u:uses]->(in_mat:material)
OPTIONAL MATCH (proc)-[pr:produces]->(out_mat:material)
WITH
  p,
  proc,
  hs,
  dev,
  coalesce(hs.order, hs.sequence, proc.stepId, proc.order, 0) AS sort_key,
  collect(DISTINCT {
    material: properties(in_mat),
    quantity: coalesce(u.quantity, 1)
  }) AS input_materials,
  collect(DISTINCT {
    material: properties(out_mat),
    quantity: coalesce(pr.quantity, 1)
  }) AS output_materials
ORDER BY sort_key
RETURN
  properties(p) AS product,
  collect({
    process: properties(proc),
    has_step: properties(hs),
    device: properties(dev),
    input_materials: input_materials,
    output_materials: output_materials,
    sort_key: sort_key
  }) AS route
```

### 设备

从 Neo4j 查询设备静态信息：

```text
device.deviceId
device.name
device.type
device.description
```

从 MySQL `device.devices` 查询设备运行信息：

```text
设备编号
设备名称
连接状态
运行状态
执行工单编号
工序编号
```

用查询结果确定每个工序的 `分配设备`。运输工单使用 AGV 设备。

### 库存物料

从 MySQL `store.materials` 查询库存物料概况：

```text
物料编号
物料名称
物料类型
库位号
```

生成 WorkOrderPlan 时使用物料语义名称和数量：

```json
{
  "material_type": "物料语义名称",
  "quantity": 1
}
```

### 已有订单和工单

从 MySQL `order.orders` 和 `order.work_orders` 查询订单是否已存在，避免生成重复 `order_id`。

需要查看：

```text
orders.订单ID
orders.产品名称
orders.订单状态
work_orders.所属订单号
work_orders.工单ID
work_orders.工单状态
```

## 生成顺序

1. 确定 `order.order_id`、`product_id`、`product_name`、`quantity`。
2. 查询产品对应的完整工艺路线。
3. 查询工艺路线中每个工序的输入物料和输出物料。
4. 查询可用设备和 AGV 设备。
5. 为每个 item 按工艺路线生成非运输工单。
6. 相邻非运输工单的 `分配设备` 不同时插入运输工单。
7. 重新编号所有工单的 `sequence`，从 1 开始连续。
8. 输出完整 JSON。

## 顶层结构

```json
{
  "order": {},
  "items": []
}
```

## order

`order` 必须包含：

```json
{
  "order_id": "PO-YYYYMMDD-001",
  "product_id": "PRODUCT-ID",
  "product_name": "产品名称",
  "quantity": 1
}
```

规则：

- `order_id` 必填。
- `product_id` 必填。
- `product_name` 必填。
- `quantity` 必填，必须是大于 0 的整数。

## items

`items` 必须是非空数组。

`items.length` 必须等于 `order.quantity`。

每个 item 必须包含：

```json
{
  "item_no": 1,
  "work_orders": []
}
```

规则：

- `item_no` 必填，必须从 1 开始连续。
- 每个 item 独立生成完整工单链路。
- 每个 item 的 `work_orders` 按同一产品工艺路线生成。

## work_orders

每个 `work_orders` 必须是非空数组。

每张工单必须包含：

```json
{
  "sequence": 1,
  "工单类型": "加工",
  "工序编号": "PROCESS-ID",
  "工单名称": "工单名称",
  "分配设备": "DEVICE-ID",
  "起始设备": "DEVICE-ID",
  "目标设备": "DEVICE-ID",
  "description": "工单说明",
  "input_materials": [],
  "output_materials": []
}
```

规则：

- `sequence` 必填，必须从 1 开始连续。
- `工单类型` 必填。
- `工序编号` 必填。
- `工单名称` 必填。
- `分配设备` 必填。
- `起始设备` 必填。
- `目标设备` 必填。
- `description` 必填。
- `input_materials` 必填，必须是数组。
- `output_materials` 必填，必须是数组。

## 工单类型

`工单类型` 只能使用：

```text
出库
加工
质检
贴标
入库
运输
```

## 工艺路线

按产品工艺路线顺序生成非运输工单。

每个非运输工单从对应工序读取并填写：

```text
工单类型 = 工序类型
工序编号 = 工序编号
工单名称 = 工序名称或根据工序生成的简短名称
分配设备 = 该工序分配的设备
起始设备 = 分配设备
目标设备 = 分配设备
description = 该工序的执行说明
input_materials = 该工序输入物料大类和数量
output_materials = 该工序输出物料大类和数量
```

非运输工单按照工艺路线原始顺序排列。

## 运输工单

相邻非运输工单的 `分配设备` 不同时，在中间插入一张运输工单。

运输工单字段：

```json
{
  "sequence": 2,
  "工单类型": "运输",
  "工序编号": "AGV-TRANSPORT",
  "工单名称": "物料运输",
  "分配设备": "AGV-DEVICE-ID",
  "起始设备": "SOURCE-DEVICE-ID",
  "目标设备": "TARGET-DEVICE-ID",
  "description": "将物料从 SOURCE-DEVICE-ID 运输到 TARGET-DEVICE-ID。",
  "input_materials": [],
  "output_materials": []
}
```

运输规则：

- 运输工单位于两个非运输工单之间。
- `工序编号` 固定为 `AGV-TRANSPORT`。
- `工单类型` 固定为 `运输`。
- `分配设备` 使用 AGV 设备。
- `起始设备` 等于前一张非运输工单的 `分配设备`。
- `目标设备` 等于后一张非运输工单的 `分配设备`。
- `input_materials` 和 `output_materials` 保持一致。
- 运输物料使用前一张非运输工单的 `output_materials`。

## 物料字段

每个物料项必须是对象：

```json
{
  "material_type": "物料语义名称",
  "quantity": 1
}
```

规则：

- `material_type` 必填。
- `quantity` 必填，必须是大于 0 的整数。
- `material_type` 使用工艺路线中物料节点的具体语义名称。
- 优先使用 Neo4j `material.name`。
- 当 Neo4j `material.name` 为空时，使用 Neo4j `material.type`。
- 示例：如果物料节点是 `{"name": "立方堆", "type": "产品"}`，则 `material_type` 填 `"立方堆"`。
- `input_materials` 来自工序输入物料需求。
- `output_materials` 来自工序输出物料定义。
- 如果工序不会改变物料形态，`output_materials` 与 `input_materials` 保持一致。

## 输出模板

```json
{
  "order": {
    "order_id": "PO-YYYYMMDD-001",
    "product_id": "PRODUCT-ID",
    "product_name": "产品名称",
    "quantity": 1
  },
  "items": [
    {
      "item_no": 1,
      "work_orders": [
        {
          "sequence": 1,
          "工单类型": "出库",
          "工序编号": "OUTPUT-001",
          "工单名称": "物料出库",
          "分配设备": "STORAGE-DEVICE-ID",
          "起始设备": "STORAGE-DEVICE-ID",
          "目标设备": "STORAGE-DEVICE-ID",
          "description": "从仓储设备出库生产所需物料。",
          "input_materials": [
            {
              "material_type": "物料大类",
              "quantity": 1
            }
          ],
          "output_materials": [
            {
              "material_type": "物料大类",
              "quantity": 1
            }
          ]
        },
        {
          "sequence": 2,
          "工单类型": "运输",
          "工序编号": "AGV-TRANSPORT",
          "工单名称": "物料运输",
          "分配设备": "AGV-DEVICE-ID",
          "起始设备": "SOURCE-DEVICE-ID",
          "目标设备": "TARGET-DEVICE-ID",
          "description": "将物料从 SOURCE-DEVICE-ID 运输到 TARGET-DEVICE-ID。",
          "input_materials": [
            {
              "material_type": "物料大类",
              "quantity": 1
            }
          ],
          "output_materials": [
            {
              "material_type": "物料大类",
              "quantity": 1
            }
          ]
        },
        {
          "sequence": 3,
          "工单类型": "加工",
          "工序编号": "PROCESS-ID",
          "工单名称": "加工工单",
          "分配设备": "DEVICE-ID",
          "起始设备": "DEVICE-ID",
          "目标设备": "DEVICE-ID",
          "description": "按工艺路线执行加工。",
          "input_materials": [
            {
              "material_type": "输入物料大类",
              "quantity": 1
            }
          ],
          "output_materials": [
            {
              "material_type": "输出物料大类",
              "quantity": 1
            }
          ]
        }
      ]
    }
  ]
}
```
