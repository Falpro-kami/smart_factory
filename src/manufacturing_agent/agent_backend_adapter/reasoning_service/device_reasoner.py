from __future__ import annotations

from typing import Any

from .rule_result import RuleResult, normalized_identity_tokens


DEVICE_PROCESS_RULE: dict[str, Any] = {
    "id": "device-process-match",
    "type": "设备匹配推理",
    "purpose": "根据产品工序能力匹配可执行设备。",
    "condition": "Product 通过 HAS_STEP 关联 Process，Process 通过 CAN_RUN_ON 关联 Device。",
    "conclusion": "工单只能分配给 ontology 中存在且具备对应产品工序能力的设备。",
    "example": "产品 -> 工序 -> 可执行设备",
    "source": "product-process",
    "target": "process",
}

STATUS_ALLOCATION_RULE: dict[str, Any] = {
    "id": "status-allocation",
    "type": "状态约束推理",
    "purpose": "判断设备是否可分配并过滤无效历史。",
    "condition": "设备存在于 ontology 设备目录，且状态不是故障、离线或维护。",
    "conclusion": "设备空闲或可用时可分配；不存在或故障设备不进入设备运行历史视图。",
    "example": "设备空闲 -> 可分配；设备故障/不存在 -> 不可分配",
    "source": "device",
    "target": "work-order",
}


DEVICE_ID_KEYS = (
    "设备ID", "设备编号", "AGV编号", "工站编号", "工作站编号", "device_id", "deviceId",
    "deviceCode", "device_code", "workstation_id", "workstationId", "station_id",
    "stationId", "agv_id", "agvId", "code", "id",
)
DEVICE_LABEL_KEYS = (
    "设备名称", "设备名", "AGV名称", "小车名称", "工站名称", "工作站名称", "device_name",
    "deviceName", "workstation_name", "workstationName", "station_name", "stationName",
    "agv_name", "agvName", "name",
)
DEVICE_SUBTITLE_KEYS = (
    "设备编号", "设备类型", "类型", "device_code", "deviceCode", "workstation_code",
    "workstationCode", "station_code", "stationCode", "agv_code", "agvCode", "code",
    "type", "device_type", "deviceType",
)


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized = {str(key).strip().lower().replace(" ", "").replace("_", "").replace("-", ""): key for key in data.keys()}
    for key in keys:
        actual = normalized.get(key.strip().lower().replace(" ", "").replace("_", "").replace("-", ""))
        if actual is None:
            continue
        value = data.get(actual)
        if value not in (None, ""):
            return value
    return None


def device_catalog_tokens(device_catalog: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for item in device_catalog:
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        values = [
            item.get("id"),
            item.get("label"),
            item.get("subtitle"),
            _first_present(props, DEVICE_ID_KEYS),
            _first_present(props, DEVICE_LABEL_KEYS),
            _first_present(props, DEVICE_SUBTITLE_KEYS),
        ]
        tokens.update(normalized_identity_tokens(values))
    return tokens


def device_history_tokens(row: dict[str, Any]) -> set[str]:
    return normalized_identity_tokens(
        [
            row.get("device_id"),
            row.get("device_name"),
            row.get("设备ID"),
            row.get("设备编号"),
            row.get("设备名称"),
            row.get("AGV编号"),
            row.get("工站编号"),
            row.get("工站名称"),
            row.get("workstation_id"),
            row.get("workstation_name"),
            row.get("agv_id"),
            row.get("agv_name"),
        ]
    )


def check_device_history(
    rows: list[dict[str, Any]],
    device_catalog: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], RuleResult]:
    known_tokens = device_catalog_tokens(device_catalog)
    if not known_tokens:
        return rows, [], RuleResult(
            rule_id="status-allocation",
            status="skipped",
            message="未读取到 ontology 设备目录，保留 MySQL 设备运行历史原始记录。",
            metrics={"knownDeviceCount": 0, "filteredOutCount": 0},
        )

    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    for row in rows:
        tokens = device_history_tokens(row)
        if tokens and tokens.intersection(known_tokens):
            valid_rows.append(row)
        else:
            invalid_rows.append(row)

    violations = [
        {
            "ruleId": "status-allocation",
            "type": "不存在的设备运行历史",
            "device_id": row.get("device_id"),
            "device_name": row.get("device_name"),
            "work_order_id": row.get("work_order_id"),
        }
        for row in invalid_rows[:50]
    ]
    return valid_rows, invalid_rows, RuleResult(
        rule_id="status-allocation",
        status="applied",
        message="设备运行历史已按 ontology 设备目录过滤，不存在的设备不会进入 DATA / Devices。",
        metrics={"knownDeviceCount": len(device_catalog), "filteredOutCount": len(invalid_rows)},
        violations=violations,
    )
