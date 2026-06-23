# Neo4j 产品工序路线标准

## 目标

Neo4j 维护产品定义、产品工序路线、工序输入输出物料、工序可执行设备。MySQL 维护订单、工单、设备实时状态和历史数据。

## 节点

### product

必需属性：

| 属性 | 说明 | 示例 |
| --- | --- | --- |
| product_id | 产品编号 | PD-CUBE-STACK |
| name | 产品名称 | 立方堆 |
| description | 产品说明 | 三个立方体堆积形成产品 |

### process

必需属性：

| 属性 | 说明 | 示例 |
| --- | --- | --- |
| process_id | 工序编号，拆单时写入工序编号 | PROC-001 |
| name | 工序名称 | 堆积工序 |
| stepId | 产品内工序顺序 | 2 |
| description | 工序说明 | 将立方体部件堆积形成产品主体 |

标准工序编号：

| 顺序 | 工序 | process_id |
| --- | --- | --- |
| 1 | 出库 | OUTPUT-001 |
| 2 | 堆积 | PROC-001 |
| 3 | 质检 | DETECT-001 |
| 4 | 贴标 | LABEL-001 |
| 5 | 入库 | INPUT-001 |

### material

建议属性：

| 属性 | 说明 | 示例 |
| --- | --- | --- |
| name | 物料/部件名称 | 立方体1 |
| type | 物料/部件类型 | 立方体 |

### device

必需属性：

| 属性 | 说明 | 示例 |
| --- | --- | --- |
| deviceId | 设备编号，建议与 MySQL `device.devices.设备编号` 一致 | DEV002 |
| name | 设备名称 | 协作加工工作站 |
| type | 设备类型 | processing |
| description | 设备说明 | 协作机器人加工工作站 |

## 关系

### 产品到工序

```cypher
(:product)-[:has_step]->(:process)
```

关系属性：

| 属性 | 说明 | 示例 |
| --- | --- | --- |
| order | 工序顺序 | 2 |
| sequence | 工序顺序兼容字段 | 2 |
| to | 指向的工序编号 | PROC-001 |

### 工序顺序

```cypher
(:process)-[:to]->(:process)
```

标准顺序：

```text
出库 OUTPUT-001 -> 堆积 PROC-001 -> 质检 DETECT-001 -> 贴标 LABEL-001 -> 入库 INPUT-001
```

### 工序使用物料

```cypher
(:process)-[:uses]->(:material)
```

### 工序产出物料

```cypher
(:process)-[:produces]->(:material)
```

### 工序可执行设备

```cypher
(:process)-[:CAN_RUN_ON]->(:device)
```

设备能力必须按产品上下文查询：

```cypher
MATCH (product:product)-[:has_step]->(process:process)-[:CAN_RUN_ON]->(device:device)
RETURN product, process, device
```

## 拆单读取约定

智能体读取产品路线时使用：

```cypher
MATCH (p:product)-[r:has_step]->(s:process)
WHERE p.product_id = $product_id
OPTIONAL MATCH (s)-[:CAN_RUN_ON]->(d:device)
OPTIONAL MATCH (s)-[:uses]->(part:material)
OPTIONAL MATCH (s)-[:produces]->(output:material)
RETURN p, r, s, d, collect(DISTINCT part) AS uses, collect(DISTINCT output) AS produces
ORDER BY coalesce(r.order, r.sequence, s.stepId)
```

拆分工单时：

- `process.process_id` 写入 MySQL `order.work_orders.工序编号`
- `process.name` 写入工序名称或工单类型
- `device.deviceId` 或 `device.name` 用于匹配 MySQL `device.devices`
- `uses` 和 `produces` 用于生成工单说明和物料追溯内容

## 立方堆示例

```text
product: 立方堆 / PD-CUBE-STACK

1. process: 出库工序 / OUTPUT-001
   device: 立体仓库
   uses: 立方体1, 立方体2, 立方体3

2. process: 堆积工序 / PROC-001
   device: 协作加工工作站
   uses: 立方体1, 立方体2, 立方体3
   produces: 立方堆产品

3. process: 质检工序 / DETECT-001
   device: scara工作站1

4. process: 贴标工序 / LABEL-001
   device: scara工作站2

5. process: 入库工序 / INPUT-001
   device: 立体仓库
```
