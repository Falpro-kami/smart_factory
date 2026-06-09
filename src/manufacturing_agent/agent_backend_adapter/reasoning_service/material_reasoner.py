from __future__ import annotations

from typing import Any


INVENTORY_CONSTRAINT_RULE: dict[str, Any] = {
    "id": "inventory-constraint",
    "type": "库存约束推理",
    "purpose": "判断物料库存是否满足生产执行。",
    "condition": "工单需求数量大于可用库存或缺少必要物料批次。",
    "conclusion": "订单或工单不可执行，并输出库存约束告警。",
    "example": "需求数量 > 库存 -> 不允许执行",
    "source": "material",
    "target": "work-order",
}
