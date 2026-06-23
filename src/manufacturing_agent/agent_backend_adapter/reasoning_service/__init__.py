from __future__ import annotations

from typing import Any

from .agv_reasoner import AGV_TASK_RULE, observe_agv_tasks
from .device_reasoner import DEVICE_PROCESS_RULE, STATUS_ALLOCATION_RULE, check_device_history
from .material_reasoner import INVENTORY_CONSTRAINT_RULE
from .order_reasoner import ORDER_SPLIT_RULE, observe_order_split
from .product_reasoner import PRODUCT_PROCESS_RULE
from .quality_reasoner import QUALITY_ROUTING_RULE, check_quality_trace


ONTOLOGY_INFERENCE_RULES: list[dict[str, Any]] = [
    PRODUCT_PROCESS_RULE,
    ORDER_SPLIT_RULE,
    DEVICE_PROCESS_RULE,
    AGV_TASK_RULE,
    INVENTORY_CONSTRAINT_RULE,
    QUALITY_ROUTING_RULE,
    STATUS_ALLOCATION_RULE,
]


def run_reasoning(
    *,
    order_rows: list[dict[str, Any]],
    device_history_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    agv_task_rows: list[dict[str, Any]],
    device_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    valid_device_rows, invalid_device_rows, device_result = check_device_history(device_history_rows, device_catalog)
    order_result = observe_order_split(order_rows)
    agv_result = observe_agv_tasks(agv_task_rows)
    quality_result = check_quality_trace(quality_rows)
    violations = [*device_result.violations, *quality_result.violations]

    return {
        "deviceHistory": valid_device_rows,
        "invalidDeviceHistory": invalid_device_rows,
        "inference": {
            "rules": ONTOLOGY_INFERENCE_RULES,
            "applied": [
                order_result.to_dict(),
                agv_result.to_dict(),
                device_result.to_dict(),
                quality_result.to_dict(),
            ],
            "violations": violations,
            "summary": {
                "validDeviceRunCount": len(valid_device_rows),
                "invalidDeviceRunCount": len(invalid_device_rows),
                "qualityExceptionCount": len(quality_result.violations),
            },
        },
    }
