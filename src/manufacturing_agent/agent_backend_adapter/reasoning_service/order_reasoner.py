from __future__ import annotations

from typing import Any

from .rule_result import RuleResult


ORDER_SPLIT_RULE: dict[str, Any] = {
    "id": "work-order-split",
    "type": "工单拆分推理",
    "purpose": "根据工艺流程生成订单下的多道工单。",
    "condition": "Order 指定 Product，Product 存在可排序工艺步骤。",
    "conclusion": "订单按步骤拆分为 Work_order，并继承产品、工序和物料约束。",
    "example": "订单 -> 多个工单",
    "source": "order",
    "target": "work-order",
}


def observe_order_split(order_rows: list[dict[str, Any]]) -> RuleResult:
    return RuleResult(
        rule_id="work-order-split",
        status="observed",
        message="已从 Data.order_work_order_history 读取订单到工单的拆分结果。",
        metrics={"workOrderCount": len(order_rows)},
    )
