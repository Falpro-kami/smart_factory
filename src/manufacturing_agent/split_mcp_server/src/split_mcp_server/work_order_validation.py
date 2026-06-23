from __future__ import annotations

import json
from datetime import datetime
from typing import Any


class WorkOrderDraftValidationError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_key(value: Any) -> str:
    return _text(value).lower().replace(" ", "").replace("_", "").replace("-", "")


def _client_sequence(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _process_id_from_step(step: dict[str, Any]) -> str:
    process = step.get("process") if isinstance(step.get("process"), dict) else {}
    return _text(
        step.get("process_id")
        or step.get("processId")
        or process.get("process_id")
        or process.get("processId")
        or process.get("code")
    )


def _process_name_from_step(step: dict[str, Any]) -> str:
    process = step.get("process") if isinstance(step.get("process"), dict) else {}
    return _text(step.get("name") or step.get("stage") or process.get("name"))


def _device_from_step(step: dict[str, Any]) -> dict[str, Any]:
    device = step.get("device") if isinstance(step.get("device"), dict) else {}
    return {
        "device_id": _text(
            device.get("device_id")
            or device.get("deviceId")
            or device.get("device_code")
            or device.get("deviceCode")
            or device.get("id")
            or device.get("code")
        ),
        "device_name": _text(
            device.get("device_name")
            or device.get("deviceName")
            or device.get("name")
        ),
        "source": "neo4j:process.can_run_on",
    }


def _device_id(device: dict[str, Any]) -> str:
    return _text(
        device.get("device_id")
        or device.get("deviceId")
        or device.get("workstation_id")
        or device.get("workstationId")
        or device.get("工站编号")
        or device.get("工作站编号")
        or device.get("设备编号")
        or device.get("id")
        or device.get("code")
    )


def _device_name(device: dict[str, Any]) -> str:
    return _text(
        device.get("device_name")
        or device.get("deviceName")
        or device.get("workstation_name")
        or device.get("workstationName")
        or device.get("工站名称")
        or device.get("工作站名称")
        or device.get("设备名称")
        or device.get("name")
    )


def _route_index(route_steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for step in route_steps:
        process_id = _process_id_from_step(step)
        if process_id:
            indexed[process_id] = step
    return indexed


def _device_index(workstations: list[dict[str, Any]], route_steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for device in workstations:
        device_id = _device_id(device)
        if device_id:
            indexed[device_id] = {
                "device_id": device_id,
                "device_name": _device_name(device) or device_id,
                "workstation_id": device_id,
                "workstation_name": _device_name(device) or device_id,
                "source": "mysql:device.devices",
            }
    for step in route_steps:
        device = _device_from_step(step)
        if device.get("device_id"):
            indexed.setdefault(device["device_id"], device)
    return indexed


def _draft_work_orders(draft: dict[str, Any]) -> list[dict[str, Any]]:
    work_orders = draft.get("work_orders") or draft.get("工单") or []
    if isinstance(work_orders, str):
        work_orders = json.loads(work_orders)
    if not isinstance(work_orders, list):
        raise WorkOrderDraftValidationError(["work_orders 必须是数组"])
    return [item for item in work_orders if isinstance(item, dict)]


def _draft_transport_requests(draft: dict[str, Any]) -> list[dict[str, Any]]:
    requests = draft.get("transport_requests") or []
    if isinstance(requests, str):
        requests = json.loads(requests)
    return [item for item in requests if isinstance(item, dict)] if isinstance(requests, list) else []


def _material_key(material: dict[str, Any]) -> str:
    return _normalize_key(
        material.get("material_id")
        or material.get("materialId")
        or material.get("物料编号")
        or material.get("material_name")
        or material.get("name")
        or material.get("物料名称")
    )


def _material_keys(material: dict[str, Any]) -> set[str]:
    keys = {
        _normalize_key(material.get("material_id") or material.get("materialId") or material.get("物料编号")),
        _normalize_key(material.get("material_name") or material.get("name") or material.get("物料名称")),
        _normalize_key(material.get("material_type") or material.get("type") or material.get("物料类型")),
    }
    requirement = material.get("requirement") if isinstance(material.get("requirement"), dict) else {}
    if requirement:
        keys.update(_material_keys(requirement))
    keys.discard("")
    return keys


def _validate_materials(
    required_materials: list[dict[str, Any]],
    allocated_materials: list[dict[str, Any]],
    order_quantity: int = 1,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not required_materials:
        warnings.append("未从订单、BOM 或工艺路线中得到明确物料需求")
        return errors, warnings

    allocated_keys: set[str] = set()
    for item in allocated_materials:
        allocated_keys.update(_material_keys(item))
    allocated_keys.discard("")
    missing = [item for item in required_materials if _material_keys(item) and _material_keys(item).isdisjoint(allocated_keys)]
    if allocated_materials and missing:
        errors.append("库存物料未完全匹配需求：" + ", ".join(_text(item.get("material_name") or item.get("name") or item.get("material_id")) for item in missing))
    for requirement in required_materials:
        requirement_keys = _material_keys(requirement)
        if not requirement_keys:
            continue
        try:
            expected_count = max(1, int(requirement.get("quantity") or 1) * max(1, order_quantity))
        except (TypeError, ValueError):
            expected_count = max(1, order_quantity)
        matched_count = sum(1 for item in allocated_materials if not _material_keys(item).isdisjoint(requirement_keys))
        if allocated_materials and matched_count < expected_count:
            label = _text(requirement.get("material_name") or requirement.get("name") or requirement.get("material_id") or requirement.get("type"))
            errors.append(f"库存物料数量不足：{label or '未命名物料'} 需要 {expected_count} 件，已分配 {matched_count} 件")
    if not allocated_materials:
        warnings.append("未能从 MySQL store 中分配到库存物料，保留 Neo4j/BOM 物料引用")
    return errors, warnings


def _transport_requested(after_sequence: int, before_sequence: int, requests: list[dict[str, Any]]) -> bool:
    for request in requests:
        after = request.get("after_client_sequence") or request.get("after_sequence")
        before = request.get("before_client_sequence") or request.get("before_sequence")
        if _client_sequence(after, -1) == after_sequence and _client_sequence(before, -1) == before_sequence:
            return True
    return False


def _material_id(material: dict[str, Any]) -> str:
    return _text(
        material.get("material_id")
        or material.get("materialId")
        or material.get("物料编号")
        or material.get("id")
        or material.get("code")
    )


def _material_name(material: dict[str, Any]) -> str:
    return _text(
        material.get("material_name")
        or material.get("materialName")
        or material.get("物料名称")
        or material.get("name")
        or _material_id(material)
    )


def _product_ref(product: dict[str, Any]) -> str:
    return _text(
        product.get("product_id")
        or product.get("productId")
        or product.get("产品编号")
        or product.get("id")
        or product.get("code")
        or product.get("name")
    )


def _stage_for_process(step: dict[str, Any], process_id: str) -> str:
    standard_stage = {
        "OUTPUT-001": "出库",
        "PROC-001": "堆积",
        "DETECT-001": "质检",
        "LABEL-001": "贴标",
        "INPUT-001": "入库",
    }.get(process_id)
    if standard_stage:
        return standard_stage
    explicit = _process_name_from_step(step)
    if explicit:
        return explicit.removesuffix("工序")
    return process_id


def _describe_step(
    *,
    order_id: str,
    product_name: str,
    step: dict[str, Any],
    process_id: str,
    stage: str,
    material_refs: list[str],
    product_refs: list[str],
) -> str:
    uses = [item for item in (step.get("uses") or []) if isinstance(item, dict)]
    produces = [item for item in (step.get("produces") or []) if isinstance(item, dict)]
    use_names = "、".join(dict.fromkeys(_material_name(item) for item in uses if _material_name(item)))
    produce_names = "、".join(dict.fromkeys(_product_ref(item) for item in produces if _product_ref(item)))
    if process_id == "OUTPUT-001" or stage == "出库":
        return f"按照订单 {order_id} 为产品 {product_name} 执行物料出库。出库物料编号：{', '.join(material_refs) or '待校验'}。"
    if process_id == "DETECT-001" or stage == "质检":
        return f"按产品 {product_name} 的工艺要求进行完工质检，确认单件产品状态。"
    if process_id == "LABEL-001" or stage == "贴标":
        return f"对质检后的产品 {product_name} 按订单 {order_id} 执行贴标，确认标签内容与单件产品一致。"
    if process_id == "INPUT-001" or stage == "入库":
        return f"贴标完成后，将产品 {product_name} 按订单 {order_id} 办理成品入库。"

    instruction = _text(
        step.get("instruction")
        or step.get("description")
        or (step.get("process") or {}).get("description")
        or "按工艺路线执行加工"
    )
    detail = []
    if use_names:
        detail.append(f"输入物料：{use_names}")
    if produce_names or product_refs:
        detail.append(f"输出产物：{produce_names or '、'.join(product_refs)}")
    suffix = "。".join(detail)
    return f"{instruction}。" + (f"{suffix}。" if suffix else "")


def _quantity_from_context(context: dict[str, Any], draft: dict[str, Any] | None = None) -> int:
    order = draft.get("order") if isinstance(draft, dict) and isinstance(draft.get("order"), dict) else {}
    try:
        return max(1, int(context.get("quantity") or (draft or {}).get("quantity") or order.get("quantity") or 1))
    except (TypeError, ValueError):
        return 1


def _item_id(order_id: str, item: dict[str, Any], item_no: int) -> str:
    return _text(item.get("item_id") or item.get("itemId") or f"{order_id}-ITEM-{item_no:03d}")


def _material_payloads_for_item(context: dict[str, Any], item_no: int, item_count: int) -> list[dict[str, Any]]:
    materials = context.get("outbound_materials") if isinstance(context.get("outbound_materials"), list) else []
    if not materials:
        return []
    selected = materials[item_no - 1::max(1, item_count)]
    return selected or materials


def _material_refs_from_payloads(materials: list[dict[str, Any]]) -> list[str]:
    refs = [_material_id(item) for item in materials if _material_id(item)]
    return list(dict.fromkeys(refs))


def _normalize_material_refs(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.replace("，", ",").replace("、", ",").split(",")]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    refs: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            ref = _material_id(item) or _material_name(item)
        else:
            ref = _text(item)
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def _append_material_description(description: str, material_payloads: list[dict[str, Any]]) -> str:
    if not material_payloads:
        return description
    details = []
    for item in material_payloads:
        material_id = _material_id(item)
        material_name = _material_name(item)
        location = _text(item.get("location") or (item.get("properties") or {}).get("库位号"))
        label = material_id
        if material_name and material_name != material_id:
            label = f"{label}({material_name})" if label else material_name
        if location:
            label = f"{label}@{location}" if label else location
        if label:
            details.append(label)
    detail_text = "、".join(dict.fromkeys(details))
    if not detail_text or detail_text in description:
        return description
    return f"{description.rstrip()} 出库/使用物料：{detail_text}。"


def build_rule_based_work_order_draft(context: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic baseline draft that used to live in the split tool."""
    product = context.get("product") if isinstance(context.get("product"), dict) else {}
    route_steps = context.get("route_steps") if isinstance(context.get("route_steps"), list) else []
    order_id = _text(context.get("order_id"))
    product_id = _text(product.get("product_id") or product.get("productId"))
    product_name = _text(product.get("name") or product.get("productName") or product_id)
    quantity = _quantity_from_context(context)
    items: list[dict[str, Any]] = []

    for item_no in range(1, quantity + 1):
        item_materials = _material_payloads_for_item(context, item_no, quantity)
        item_work_orders: list[dict[str, Any]] = []
        for index, step in enumerate(route_steps, start=1):
            process_id = _process_id_from_step(step)
            stage = _stage_for_process(step, process_id)
            uses = [item for item in (step.get("uses") or []) if isinstance(item, dict)]
            produces = [item for item in (step.get("produces") or []) if isinstance(item, dict)]
            material_refs = [_material_id(item) for item in uses if _material_id(item)]
            if process_id in {"OUTPUT-001", "PROC-001"} and item_materials:
                material_refs = _material_refs_from_payloads(item_materials)
            product_refs = [_product_ref(item) for item in produces if _product_ref(item)]
            device = _device_from_step(step)
            description = _describe_step(
                order_id=order_id,
                product_name=product_name,
                step=step,
                process_id=process_id,
                stage=stage,
                material_refs=material_refs,
                product_refs=product_refs,
            )
            if process_id in {"OUTPUT-001", "PROC-001"}:
                description = _append_material_description(description, item_materials)
            item_work_orders.append(
                {
                    "client_sequence": index,
                    "sequence": index,
                    "draft_type": "process",
                    "stage": stage,
                    "工单类型": stage,
                    "title": f"{product_name}{stage}",
                    "工单名称": f"{product_name}{stage}",
                    "process_id": process_id,
                    "工序编号": process_id,
                    "assigned_device_id": device.get("device_id"),
                    "assigned_device_name": device.get("device_name"),
                    "分配设备": device.get("device_id"),
                    "source_station": device.get("device_id"),
                    "target_station": device.get("device_id"),
                    "起始工站": device.get("device_id"),
                    "目标工站": device.get("device_id"),
                    "predecessor_ref": f"client_sequence:{index - 1}" if index > 1 else None,
                    "successor_ref": f"client_sequence:{index + 1}" if index < len(route_steps) else None,
                    "description": description,
                    "material_refs": material_refs,
                    "materials": material_refs,
                    "product_refs": product_refs,
                }
            )
        items.append(
            {
                "item_no": item_no,
                "item_id": f"{order_id}-ITEM-{item_no:03d}",
                "work_orders": item_work_orders,
            }
        )

    return {
        "draft_version": "rule-based-1.0",
        "order": {
            "order_id": order_id,
            "product_id": product_id,
            "product_name": product_name,
            "quantity": quantity,
        },
        "items": items,
        "validation_notes": [],
    }


def _draft_item_entries(draft: dict[str, Any], context: dict[str, Any], order_id: str) -> list[dict[str, Any]]:
    raw_items = draft.get("items") or []
    if isinstance(raw_items, str):
        raw_items = json.loads(raw_items)
    if isinstance(raw_items, list) and raw_items:
        return [item for item in raw_items if isinstance(item, dict)]
    return [
        {
            "item_no": 1,
            "item_id": draft.get("item_id") or f"{order_id}-ITEM-001",
            "work_orders": _draft_work_orders(draft),
            "transport_requests": _draft_transport_requests(draft),
        }
    ]


def _transport_title(previous_stage: str, next_stage: str) -> str:
    if previous_stage == "出库" and next_stage in {"加工", "堆积"}:
        return "出库物料运输至加工"
    if previous_stage in {"加工", "堆积"} and next_stage == "质检":
        return "加工后产品运输至质检"
    if previous_stage == "质检" and next_stage == "贴标":
        return "质检后产品运输至贴标"
    if previous_stage == "贴标" and next_stage == "入库":
        return "贴标后产品运输至入库"
    return f"{previous_stage}运输至{next_stage}"


def validate_and_complete_work_order_draft(draft: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Validate an agent work-order draft and return final MySQL-ready work orders."""
    if not isinstance(draft, dict):
        raise WorkOrderDraftValidationError(["工单草案必须是 JSON 对象"])

    errors: list[str] = []
    warnings: list[str] = []
    order = draft.get("order") if isinstance(draft.get("order"), dict) else {}
    product = context.get("product") if isinstance(context.get("product"), dict) else {}
    route_steps = context.get("route_steps") if isinstance(context.get("route_steps"), list) else []
    workstations = context.get("workstations") if isinstance(context.get("workstations"), list) else []
    required_materials = context.get("required_materials") if isinstance(context.get("required_materials"), list) else []
    allocated_materials = context.get("allocated_materials") if isinstance(context.get("allocated_materials"), list) else []

    order_id = _text(draft.get("order_id") or order.get("order_id") or context.get("order_id"))
    product_id = _text(draft.get("product_id") or order.get("product_id") or product.get("product_id") or product.get("productId"))
    product_name = _text(draft.get("product_name") or order.get("product_name") or product.get("name") or product.get("productName") or product_id)
    quantity = _quantity_from_context(context, draft)
    agv_id = _text(context.get("agv_id") or "DEV005")
    pallet_id = _text(context.get("pallet_id") or f"{order_id}-PALLET")

    if not order_id:
        errors.append("缺少订单编号 order_id")
    if not product_name:
        errors.append("缺少产品名称")

    route_by_process = _route_index(route_steps)
    route_process_ids = set(route_by_process.keys())
    route_order = {process_id: index for index, process_id in enumerate(route_by_process.keys(), start=1)}
    devices = _device_index(workstations, route_steps)
    item_entries = _draft_item_entries(draft, context, order_id)
    if quantity != len(item_entries):
        warnings.append(f"订单数量为 {quantity}，items 数量为 {len(item_entries)}，以 items 实际数量生成工单。")
        quantity = len(item_entries) or quantity

    material_errors, material_warnings = _validate_materials(required_materials, allocated_materials, quantity)
    errors.extend(material_errors)
    warnings.extend(material_warnings)

    all_work_orders: list[dict[str, Any]] = []
    completed_items: list[dict[str, Any]] = []
    include_transport = context.get("include_transport", True) is not False

    for item_index, item_entry in enumerate(item_entries, start=1):
        item_no = _client_sequence(item_entry.get("item_no") or item_entry.get("itemNo"), item_index)
        item_id = _item_id(order_id, item_entry, item_no)
        item_materials = _material_payloads_for_item(context, item_index, max(1, len(item_entries)))
        draft_items = _draft_work_orders(item_entry)
        if not draft_items:
            errors.append(f"{item_id} 没有 work_orders")
            continue

        seen_process_ids: set[str] = set()
        draft_process_ids = {
            _text(item.get("process_id") or item.get("工序编号"))
            for item in draft_items
            if _text(item.get("工单类型") or item.get("stage")) != "运输"
            and _text(item.get("process_id") or item.get("工序编号")) != "AGV-TRANSPORT"
        }
        missing_process_ids = [process_id for process_id in route_order if process_id not in draft_process_ids]
        if missing_process_ids:
            errors.append(f"{item_id} 工单链不完整，缺少工序：{', '.join(missing_process_ids)}")

        def sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[int, int]:
            fallback_sequence, item = pair
            process_id = _text(item.get("process_id") or item.get("工序编号"))
            client_sequence = _client_sequence(item.get("client_sequence") or item.get("sequence"), fallback_sequence)
            return (route_order.get(process_id, 1_000_000 + client_sequence), client_sequence)

        normalized_process_items: list[dict[str, Any]] = []
        for fallback_sequence, item in sorted(enumerate(draft_items, start=1), key=sort_key):
            client_sequence = _client_sequence(item.get("client_sequence") or item.get("sequence"), fallback_sequence)
            raw_stage = _text(item.get("stage") or item.get("工单类型") or item.get("name"))
            process_id = _text(item.get("process_id") or item.get("工序编号"))
            if raw_stage == "运输" or process_id == "AGV-TRANSPORT":
                warnings.append(f"{item_id} 草案中的运输工单由校验层按设备变化重新生成：sequence={client_sequence}")
                continue
            if not process_id and route_steps and client_sequence <= len(route_steps):
                process_id = _process_id_from_step(route_steps[client_sequence - 1])
            route_step = route_by_process.get(process_id, {})
            stage = raw_stage or _stage_for_process(route_step, process_id)
            if route_process_ids and process_id and process_id not in route_process_ids:
                errors.append(f"{item_id} 工序 {process_id} 不属于当前产品 Neo4j 工艺路线")
            if not process_id:
                errors.append(f"{item_id} 第 {client_sequence} 条工单缺少工序编号 process_id")
            if process_id and process_id in seen_process_ids:
                errors.append(f"{item_id} 重复工序编号：{process_id}")
            if process_id:
                seen_process_ids.add(process_id)

            draft_assigned_device = item.get("assigned_device") if isinstance(item.get("assigned_device"), dict) else {}
            assigned_device_id = _text(
                item.get("assigned_device_id")
                or item.get("分配设备")
                or item.get("分配工站")
                or _device_id(draft_assigned_device)
                or _device_from_step(route_step).get("device_id")
            )
            assigned_device = devices.get(assigned_device_id, {})
            if assigned_device_id and not assigned_device:
                errors.append(f"{item_id} 设备不存在或未在 MySQL/Neo4j 上下文中找到：{assigned_device_id}")
                assigned_device = {"device_id": assigned_device_id, "device_name": _text(item.get("assigned_device_name")) or assigned_device_id}
            if not assigned_device_id:
                errors.append(f"{item_id} 工序 {process_id or client_sequence} 缺少分配设备")

            title = _text(item.get("title") or item.get("工单名称"))
            expected_title = f"{product_name}{stage}" if product_name and stage else title
            if title and expected_title and title != expected_title:
                warnings.append(f"{item_id} 工单名称已修正：{title} -> {expected_title}")
            title = expected_title or title or f"{product_name}{process_id}"
            assigned_station = assigned_device.get("device_id") or assigned_device_id
            description = _text(item.get("description") or item.get("content"))
            if not description:
                description = _describe_step(
                    order_id=order_id,
                    product_name=product_name,
                    step=route_step,
                    process_id=process_id,
                    stage=stage,
                    material_refs=_material_refs_from_payloads(item_materials),
                    product_refs=[],
                )
            raw_material_refs = (
                item.get("material_refs")
                or item.get("material_ids")
                or item.get("materials")
                or []
            )
            material_refs = _normalize_material_refs(raw_material_refs)
            if process_id in {"OUTPUT-001", "PROC-001"} and item_materials:
                material_refs = list(dict.fromkeys([*material_refs, *_material_refs_from_payloads(item_materials)]))
                description = _append_material_description(description, item_materials)

            normalized_process_items.append(
                {
                    "client_sequence": client_sequence,
                    "item_no": item_no,
                    "item_id": item_id,
                    "source_order_id": order_id,
                    "stage": stage,
                    "title": title,
                    "content": description,
                    "description": description,
                    "product_id": product_id,
                    "product_name": product_name,
                    "quantity": 1,
                    "status": "已创建",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "task_type": _text(item.get("draft_type") or item.get("task_type") or "process"),
                    "process_id": process_id,
                    "process_name": stage,
                    "assigned_device": {
                        "device_id": assigned_station,
                        "device_name": assigned_device.get("device_name") or _text(item.get("assigned_device_name")) or assigned_station,
                        "workstation_id": assigned_station,
                        "workstation_name": assigned_device.get("workstation_name") or assigned_device.get("device_name") or assigned_station,
                        "source": assigned_device.get("source") or "validation:completed",
                    },
                    "source_station": assigned_station,
                    "target_station": assigned_station,
                    "material_ids": material_refs,
                    "materials": material_refs,
                    "product_refs": item.get("product_refs") or [],
                }
            )

        if errors:
            continue

        transport_requests = _draft_transport_requests(item_entry)
        final_item_work_orders: list[dict[str, Any]] = []
        sequence = 1
        for index, item in enumerate(normalized_process_items):
            item["sequence"] = sequence
            item["work_order_id"] = f"{item_id}-WO-{sequence:03d}"
            final_item_work_orders.append(item)
            sequence += 1

            next_item = normalized_process_items[index + 1] if index + 1 < len(normalized_process_items) else None
            if not next_item or not include_transport:
                continue
            current_station = _text(item.get("target_station") or item["assigned_device"]["device_id"])
            next_station = _text(next_item.get("source_station") or next_item["assigned_device"]["device_id"])
            needs_transport = bool(current_station and next_station and current_station != next_station)
            if not needs_transport and not _transport_requested(item["client_sequence"], next_item["client_sequence"], transport_requests):
                continue
            transport_title = _transport_title(item.get("stage") or "", next_item.get("stage") or "")
            description = (
                f"前置工单 {item['work_order_id']} 完成后，调度 {agv_id} 将物料盘 {pallet_id} "
                f"从 {current_station} 转运到 {next_station}。"
            )
            final_item_work_orders.append(
                {
                    "work_order_id": f"{item_id}-AGV-{sequence:03d}",
                    "item_no": item_no,
                    "item_id": item_id,
                    "source_order_id": order_id,
                    "sequence": sequence,
                    "stage": "运输",
                    "title": transport_title,
                    "content": description,
                    "description": description,
                    "product_id": product_id,
                    "product_name": product_name,
                    "quantity": 1,
                    "status": "已创建",
                    "task_type": "agv_transport",
                    "process_id": "AGV-TRANSPORT",
                    "process_name": "运输",
                    "assigned_device": {
                        "device_id": agv_id,
                        "device_name": agv_id,
                        "workstation_id": agv_id,
                        "workstation_name": agv_id,
                        "source": "validation:agv",
                    },
                    "source_station": current_station,
                    "target_station": next_station,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            sequence += 1

        for index, item in enumerate(final_item_work_orders):
            predecessor = final_item_work_orders[index - 1]["work_order_id"] if index > 0 else None
            successor = final_item_work_orders[index + 1]["work_order_id"] if index + 1 < len(final_item_work_orders) else None
            item["predecessor_work_order_id"] = predecessor
            item["successor_work_order_id"] = successor
            assigned_station = _text((item.get("assigned_device") or {}).get("device_id"))
            item["工单ID"] = item["work_order_id"]
            item["工单名称"] = item["title"]
            item["所属订单号"] = order_id
            item["工单类型"] = item["stage"]
            item["工序编号"] = item["process_id"]
            item["前置工单"] = predecessor
            item["后续工单"] = successor
            item["分配设备"] = assigned_station
            item["起始工站"] = item.get("source_station") or assigned_station
            item["目标工站"] = item.get("target_station") or assigned_station
            item["工单状态"] = "已创建"

        all_work_orders.extend(final_item_work_orders)
        completed_items.append({"item_no": item_no, "item_id": item_id, "work_orders": final_item_work_orders})

    if errors:
        raise WorkOrderDraftValidationError(errors, warnings)

    return {
        "success": True,
        "order_id": order_id,
        "product": product,
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "items": completed_items,
        "work_orders": all_work_orders,
        "work_order_count": len(all_work_orders),
        "agv_transport_count": sum(1 for item in all_work_orders if item.get("task_type") == "agv_transport"),
        "validation": {
            "ok": True,
            "warnings": warnings,
            "errors": [],
            "source": "work_order_validation",
        },
    }
