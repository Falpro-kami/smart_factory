from __future__ import annotations

from typing import Any

from .rule_result import RuleResult


AGV_TASK_RULE: dict[str, Any] = {
    "id": "agv-task",
    "type": "AGV 任务推理",
    "purpose": "判断相邻工单或仓储节点之间是否需要运输。",
    "condition": "首道工序、相邻工单设备不同、末道工序入库。",
    "conclusion": "生成仓库到工站、工站间转运或工站到仓库的 AGV 任务。",
    "example": "相邻工单设备不同 -> 生成 AGV 任务",
    "source": "work-order",
    "target": "agv",
}


def observe_agv_tasks(agv_task_rows: list[dict[str, Any]]) -> RuleResult:
    return RuleResult(
        rule_id="agv-task",
        status="observed",
        message="已从 AGV.tasks 读取或生成运输任务。",
        metrics={"agvTaskCount": len(agv_task_rows)},
    )
