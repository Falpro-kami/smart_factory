from __future__ import annotations

from typing import Any

from .rule_result import RuleResult, normalize_text


QUALITY_ROUTING_RULE: dict[str, Any] = {
    "id": "quality-routing",
    "type": "质量规则推理",
    "purpose": "根据质检结果判断入库、返工或异常处理。",
    "condition": "Quality trace 中检验结果为不合格或异常。",
    "conclusion": "工单进入返工或异常状态，不进入正常入库流程。",
    "example": "质检不合格 -> 返工/异常",
    "source": "work-order",
    "target": "product",
}


def check_quality_trace(quality_rows: list[dict[str, Any]]) -> RuleResult:
    failed_quality = [
        row for row in quality_rows
        if "不合格" in normalize_text(row.get("inspection_result") or row.get("检验结果") or "")
    ]
    violations = [
        {
            "ruleId": "quality-routing",
            "type": "质检不合格",
            "inspection_id": row.get("inspection_id"),
            "product_id": row.get("product_id"),
            "work_order_id": row.get("work_order_id"),
        }
        for row in failed_quality[:50]
    ]
    return RuleResult(
        rule_id="quality-routing",
        status="observed",
        message="已读取质检追溯记录，质检不合格记录进入返工或异常判断。",
        metrics={"failedQualityCount": len(failed_quality)},
        violations=violations,
    )
