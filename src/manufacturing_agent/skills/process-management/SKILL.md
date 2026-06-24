---
name: process-management
description: 用于在 Neo4j 中录入、修改和核查产品、工序、物料、设备能力关系。适用于新增产品工艺路线、维护 process/material/device 节点、维护 has_step/uses/produces/CAN_RUN_ON 关系，以及为后续 WorkOrderPlan 生成准备工艺数据。
---

# 工艺管理

处理工艺数据时，先查询现有 Neo4j 数据，再决定新增或更新。缺少必要信息时先向用户确认，不要擅自生成产品 ID、物料名称、设备、description 或关系属性。工序名称、数量和物料 type 可以从用户表达和工艺上下文中解析；表达不清或互相矛盾时再询问。

## 数据模型

使用以下标签和关系：

```text
product
process
material
device

(product)-[:has_step {order}]->(process)
(process)-[:uses {quantity}]->(material)
(process)-[:produces {quantity}]->(material)
(process)-[:CAN_RUN_ON]->(device)
```

## 必要信息

新增产品前必须明确：

```text
product_id
product_name
加工工序列表
每道工序的 process_id
每道工序的顺序 order
每道工序的执行设备 deviceId
每道工序的输入物料和 quantity
每道工序的输出物料和 quantity
```

如果用户没有提供以上任一信息，先提问确认。工序名称、数量和物料 type 除外：如果用户表达或工艺上下文中可以明确推断，直接使用推断结果。

## 工序名称生成

如果用户没有显式提供工序名称，按工序语义生成简短名称，不需要追问。

命名规则：

```text
优先使用“核心输出物料 + 动作”
动作从用户表达中提取，例如组装、加工、检测、贴标
名称保持简短，避免长句
```

示例：

```text
将两对轮胎和底盘进行组装，输出轮胎底盘总成 -> 轮胎底盘总成组装
将车身和轮胎底盘总成组装，输出车身总成 -> 车身总成组装
将车顶和车身总成组装，输出乐高小汽车 -> 乐高小汽车组装
```

只有在无法判断核心输出物料或动作时才询问用户。

## 数量解析

从用户表达中解析物料数量：

```text
一个 / 一件 / 一套 / 单个 -> quantity=1
两个 / 两件 / 两个单位 -> quantity=2
一对 -> quantity=2
两对 -> quantity=4
三对 -> quantity=6
```

如果用户同时给出自然语言数量和括号中的显式数量，以显式数量为准，除非两者明显冲突。

如果用户定义了计量单位，按用户定义解析数量。

示例：

```text
两对轮胎 -> 轮胎 quantity=4
一对轮胎算一个物料，两对轮胎 -> 轮胎 quantity=2
两对轮胎（轮胎数量为2），但未说明一对算一个物料 -> 数量冲突，先询问用户确认
车身数量1 -> 车身 quantity=1
车顶数量为1 -> 车顶 quantity=1
```

## 物料 type 推断

`material.type` 只能使用：

```text
原材料
半成品
成品
```

根据工艺上下文推断物料 type：

```text
只作为输入物料出现，且不是前序工序产物 -> 原材料
某道工序输出，且会被后续工序继续使用 -> 半成品
最后一道加工工序的最终输出，且名称等于产品名称 -> 成品
明确表达为总成、组件、中间产物 -> 半成品
明确表达为最终产品、成品，或等于产品名称 -> 成品
```

示例：

```text
轮胎、底盘、车身、车顶只作为输入物料出现 -> 原材料
轮胎底盘总成先被产生、后被使用 -> 半成品
车身总成先被产生、后被使用 -> 半成品
乐高小汽车是最后输出且等于产品名称 -> 成品
```

只有在无法通过上下文唯一判断时才询问用户。

固定流程不要求用户提供：

```text
出库
质检
贴标
入库
```

产品工艺录入时，用户只需要提供产品的加工工序。智能体必须自动把固定流程加入产品 `has_step` 路线。

完整产品路线顺序：

```text
1. OUTPUT-001 出库
2..N. 用户提供的加工工序，按用户描述顺序排列
N+1. DETECT-001 质检
N+2. LABEL-001 贴标
N+3. INPUT-001 入库
```

运输不写入产品 `has_step` 路线；运输工单由后续 WorkOrderPlan 生成阶段根据相邻工单设备变化自动插入。

固定工序对应关系：

```text
OUTPUT-001 -> DEV001
DETECT-001 -> DEV003
LABEL-001 -> DEV004
INPUT-001 -> DEV001
```

固定工序是全局流程能力，只加入产品 `has_step` 路线，不写产品物料关系：

```text
不要为 OUTPUT-001 写 uses / produces
不要为 DETECT-001 写 uses / produces
不要为 LABEL-001 写 uses / produces
不要为 INPUT-001 写 uses / produces
```

固定工序的物料语义由 WorkOrderPlan 生成/校验阶段根据加工工序推断：

```text
出库物料 = 加工链路中所有原材料输入
质检物料 = 最终加工输出
贴标物料 = 最终加工输出
入库物料 = 最终加工输出
```

## 查询顺序

一次性查清当前状态：

```cypher
MATCH (p:product)
OPTIONAL MATCH (p)-[hs:has_step]->(proc:process)
OPTIONAL MATCH (proc)-[u:uses]->(in_mat:material)
OPTIONAL MATCH (proc)-[pr:produces]->(out_mat:material)
OPTIONAL MATCH (proc)-[cr:CAN_RUN_ON]->(dev:device)
RETURN
  properties(p) AS product,
  collect(DISTINCT {
    process: properties(proc),
    has_step: properties(hs),
    input_material: properties(in_mat),
    uses: properties(u),
    output_material: properties(out_mat),
    produces: properties(pr),
    device: properties(dev)
  }) AS route
```

查询指定产品时使用：

```cypher
MATCH (p:product)
WHERE p.product_id = $product_id OR p.name = $product_name
RETURN properties(p) AS product
```

查询指定设备能力时使用：

```cypher
MATCH (proc:process)-[r:CAN_RUN_ON]->(dev:device)
WHERE proc.process_id IN $process_ids OR dev.deviceId IN $device_ids
RETURN proc.process_id AS process_id, dev.deviceId AS device_id, properties(dev) AS device
```

## 写入规则

写入必须使用绑定节点后的 `MERGE`，避免重复节点和重复关系。不要使用 `CREATE` 创建产品、工序、物料、设备或这些关系。

产品节点：

```cypher
MERGE (p:product {product_id: $product_id})
SET p.name = $product_name
```

工序节点：

```cypher
MERGE (proc:process {process_id: $process_id})
SET proc.name = $process_name
```

物料节点：

```cypher
MERGE (mat:material {name: $material_name})
SET mat.type = $material_type
```

如果用户没有显式提供 `material_type`，按“物料 type 推断”规则确定。

设备节点：

```cypher
MERGE (dev:device {deviceId: $device_id})
```

产品工艺路线：

```cypher
MATCH (p:product {product_id: $product_id})
MATCH (proc:process {process_id: $process_id})
MERGE (p)-[hs:has_step]->(proc)
SET hs.order = $order
```

输入物料：

```cypher
MATCH (proc:process {process_id: $process_id})
MATCH (mat:material {name: $material_name})
MERGE (proc)-[u:uses]->(mat)
SET u.quantity = $quantity
```

输出物料：

```cypher
MATCH (proc:process {process_id: $process_id})
MATCH (mat:material {name: $material_name})
MERGE (proc)-[pr:produces]->(mat)
SET pr.quantity = $quantity
```

设备能力：

```cypher
MATCH (proc:process {process_id: $process_id})
MATCH (dev:device {deviceId: $device_id})
MERGE (proc)-[:CAN_RUN_ON]->(dev)
```

写入前先查询目标关系是否已存在；写入后必须检查重复关系：

```cypher
MATCH (a)-[r]->(b)
WHERE type(r) IN ['has_step', 'uses', 'produces', 'CAN_RUN_ON']
WITH elementId(a) AS start_id, elementId(b) AS end_id, type(r) AS rel_type, count(r) AS rel_count
WHERE rel_count > 1
RETURN start_id, end_id, rel_type, rel_count
```

如果当前写入造成重复关系，保留一条，删除多余关系。

## 新增产品格式

用户提供新产品时，整理成这种结构后再写入：

```json
{
  "product_id": "PD-...",
  "product_name": "产品名称",
  "steps": [
    {
      "order": 2,
      "process_id": "PROC-...",
      "device_id": "DEV...",
      "uses": [
        {"material_name": "物料A", "material_type": "原材料", "quantity": 1}
      ],
      "produces": [
        {"material_name": "中间产物A", "material_type": "半成品", "quantity": 1}
      ]
    }
  ]
}
```

## 乐高小汽车示例

用户要求录入“乐高小汽车”时，如果没有给 `product_id`，先确认 `product_id`，不要擅自生成。

已知加工工序可整理为：

```text
产品名称：乐高小汽车

固定出库、质检、贴标、入库流程不需要用户说明，但必须写入该产品的 `has_step` 路线。运输不写入产品路线。

order=1
process_id=OUTPUT-001
device_id=DEV001

order=2
process_id=PROC-008
device_id=DEV002
uses:
- 轮胎 type=原材料 quantity=2
- 底盘 type=原材料 quantity=1
produces:
- 轮胎底盘总成 type=半成品 quantity=1

order=3
process_id=PROC-006
device_id=DEV010
uses:
- 车身 type=原材料 quantity=1
- 轮胎底盘总成 type=半成品 quantity=1
produces:
- 车身总成 type=半成品 quantity=1

order=4
process_id=PROC-004
device_id=DEV008
uses:
- 车顶 type=原材料 quantity=1
- 车身总成 type=半成品 quantity=1
produces:
- 乐高小汽车 type=成品 quantity=1

order=5
process_id=DETECT-001
device_id=DEV003

order=6
process_id=LABEL-001
device_id=DEV004

order=7
process_id=INPUT-001
device_id=DEV001
```

## 校验

写入后必须回查：

```cypher
MATCH (p:product {product_id: $product_id})-[hs:has_step]->(proc:process)
OPTIONAL MATCH (proc)-[u:uses]->(in_mat:material)
OPTIONAL MATCH (proc)-[pr:produces]->(out_mat:material)
OPTIONAL MATCH (proc)-[:CAN_RUN_ON]->(dev:device)
RETURN
  p.product_id AS product_id,
  p.name AS product_name,
  hs.order AS order,
  proc.process_id AS process_id,
  collect(DISTINCT {name: in_mat.name, quantity: u.quantity}) AS uses,
  collect(DISTINCT {name: out_mat.name, quantity: pr.quantity}) AS produces,
  collect(DISTINCT dev.deviceId) AS devices
ORDER BY order
```

确认：

- `has_step.order` 连续且顺序正确。
- 产品路线必须包含固定工序 `OUTPUT-001`、`DETECT-001`、`LABEL-001`、`INPUT-001`。
- 每个工序都有执行设备。
- 每个 `uses` 和 `produces` 关系都有 `quantity`。
- 每个物料节点都有 `type`，且只能是 `原材料`、`半成品`、`成品`。
- 中间产物名称前后一致。
- 不存在重复的 `has_step`、`uses`、`produces`、`CAN_RUN_ON` 关系。
- 未写入用户未确认的字段。
