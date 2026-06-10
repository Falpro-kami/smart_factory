"""Runtime scheduler boundary for order dispatch.

The device event consumer owns event ingestion and state updates. This module
owns scheduler triggers, queue draining, and the bridge to the dispatch core.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any


TERMINAL_WORK_ORDER_STATUSES = {"已完成", "失败"}


def work_order_scheduler(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one dispatch pass for a single production order."""
    from split_mcp_server.server import (
        build_work_order_delivery_message,
        clean_value,
        dependency_check,
        device_is_online_idle,
        ensure_order_status_schema,
        fetch_device_runtime,
        fetch_scheduler_candidates,
        get_mysql_connection,
        notify_digital_twin_event,
        order_id_column,
        record_work_order_delivery_log,
        safe_column_name,
        scheduler_delivery_arguments,
        send_rocketmq_message,
        set_work_order_status,
    )

    order_id = str(arguments.get("order_id") or arguments.get("orderId") or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    limit = max(1, min(int(arguments.get("limit") or arguments.get("max_dispatch") or 20), 100))
    event_time = datetime.now()
    results: list[dict[str, Any]] = []

    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            candidates = fetch_scheduler_candidates(cursor, order_id, limit)
            for work_order in candidates:
                work_order_id = str(work_order.get("work_order_id") or "")
                dependencies = dependency_check(cursor, work_order)
                if not dependencies["ready"]:
                    updated = set_work_order_status(cursor, work_order_id, "受阻", event_time)
                    results.append(
                        {
                            "work_order_id": work_order_id,
                            "action": "blocked",
                            "reason": "dependencies_unmet",
                            "updated_rows": updated,
                            **dependencies,
                        }
                    )
                    continue

                device_id = str(work_order.get("device_id") or "").strip()
                if not device_id:
                    updated = set_work_order_status(cursor, work_order_id, "受阻", event_time)
                    results.append(
                        {
                            "work_order_id": work_order_id,
                            "action": "blocked",
                            "reason": "missing_target_device",
                            "updated_rows": updated,
                            **dependencies,
                        }
                    )
                    continue

                device = fetch_device_runtime(device_id)
                if not device_is_online_idle(device):
                    updated = set_work_order_status(cursor, work_order_id, "受阻", event_time)
                    results.append(
                        {
                            "work_order_id": work_order_id,
                            "action": "blocked",
                            "reason": "device_not_online_idle",
                            "device_id": device_id,
                            "device": clean_value(device),
                            "updated_rows": updated,
                            **dependencies,
                        }
                    )
                    continue

                delivery_arguments = scheduler_delivery_arguments(work_order)
                try:
                    message_payload = build_work_order_delivery_message(delivery_arguments)
                    send_result = send_rocketmq_message(message_payload)
                    record_work_order_delivery_log(message_payload, send_result)
                    status_updated = set_work_order_status(cursor, work_order_id, "已下发", event_time)
                    cursor.execute(
                        f"""
                        UPDATE `orders`
                        SET `订单状态` = '已下发'
                        WHERE {order_id_col} = %s AND `订单状态` IN ('已创建', '已计划')
                        """,
                        (order_id,),
                    )
                    results.append(
                        {
                            "work_order_id": work_order_id,
                            "action": "dispatched",
                            "device_id": device_id,
                            "status_updated_rows": status_updated,
                            **dependencies,
                            **message_payload,
                            **send_result,
                        }
                    )
                except Exception as exc:
                    updated = set_work_order_status(cursor, work_order_id, "受阻", event_time)
                    results.append(
                        {
                            "work_order_id": work_order_id,
                            "action": "blocked",
                            "reason": "delivery_failed",
                            "error": str(exc),
                            "updated_rows": updated,
                            **dependencies,
                        }
                    )
            conn.commit()

    dispatched = [item for item in results if item.get("action") == "dispatched"]
    blocked = [item for item in results if item.get("action") == "blocked"]
    summary = {
        "candidate_count": len(results),
        "dispatched_count": len(dispatched),
        "blocked_count": len(blocked),
        "updated_at": event_time.isoformat(timespec="seconds"),
    }
    notify_digital_twin_event(
        "work_order_scheduler_ran",
        {"order_id": order_id, **summary},
    )
    return {
        "success": True,
        "tool": "WorkOrderScheduler",
        "order_id": order_id,
        "summary": summary,
        "results": results,
    }


def run_scheduler_queue_once(limit: int = 20) -> dict[str, Any]:
    """Drain queued orders and run one scheduler pass for each."""
    from split_mcp_server.server import (
        SCHEDULER_QUEUE_TABLE,
        ensure_scheduler_queue_schema,
        get_mysql_connection,
        order_status_for_scheduler,
        scheduler_queue_rows,
    )

    run_at = datetime.now()
    runs: list[dict[str, Any]] = []
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_scheduler_queue_schema(cursor)
            rows = scheduler_queue_rows(cursor, limit)
        conn.commit()

    for row in rows:
        order_id = str(row.get("order_id") or "")
        if not order_id:
            continue
        try:
            result = work_order_scheduler({"order_id": order_id})
            summary = result.get("summary") if isinstance(result, dict) else {}
            with get_mysql_connection("order") as conn:
                with conn.cursor() as cursor:
                    status = order_status_for_scheduler(cursor, order_id)
                    queue_status = "active"
                    if status == "已完成":
                        queue_status = "completed"
                    elif status == "失败":
                        queue_status = "failed"
                    cursor.execute(
                        f"""
                        UPDATE {SCHEDULER_QUEUE_TABLE}
                        SET queue_status = %s,
                            updated_at = %s,
                            last_run_at = %s,
                            last_summary_json = %s
                        WHERE order_id = %s
                        """,
                        (
                            queue_status,
                            run_at,
                            run_at,
                            json.dumps(summary, ensure_ascii=False),
                            order_id,
                        ),
                    )
                conn.commit()
            runs.append({"order_id": order_id, "queue_status": queue_status, "summary": summary})
        except Exception as exc:
            with get_mysql_connection("order") as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE {SCHEDULER_QUEUE_TABLE}
                        SET queue_status = 'active',
                            updated_at = %s,
                            last_run_at = %s,
                            last_summary_json = %s
                        WHERE order_id = %s
                        """,
                        (
                            run_at,
                            run_at,
                            json.dumps({"error": str(exc)}, ensure_ascii=False),
                            order_id,
                        ),
                    )
                conn.commit()
            runs.append({"order_id": order_id, "queue_status": "active", "error": str(exc)})

    return {
        "success": True,
        "tool": "SchedulerQueueDrain",
        "run_at": run_at.isoformat(timespec="seconds"),
        "processed_count": len(runs),
        "runs": runs,
    }


def drain_scheduler_queue(limit: int = 20) -> dict:
    """Drain submitted scheduler orders once."""
    return run_scheduler_queue_once(limit=limit)


def trigger_after_workorder_event(order_id: str, status: str, limit: int = 20) -> None:
    """Re-queue an order and run the scheduler after a terminal work-order event."""
    if not order_id or status not in TERMINAL_WORK_ORDER_STATUSES:
        return
    try:
        from split_mcp_server.server import submit_order_to_scheduler

        submit_order_to_scheduler({"order_id": order_id})
        result = drain_scheduler_queue(limit=limit)
        summary = result.get("summary") if isinstance(result, dict) else {}
        print(
            f"scheduler queue triggered after work order event: order_id={order_id}, summary={summary}",
            file=sys.stderr,
            flush=True,
        )
    except Exception as exc:
        print(f"scheduler trigger skipped for order {order_id}: {exc}", file=sys.stderr, flush=True)


def run_scheduler_queue_tick(limit: int = 20) -> None:
    """Periodic scheduler tick used by the runtime service loop."""
    try:
        result = drain_scheduler_queue(limit=limit)
        processed_count = int(result.get("processed_count") or 0) if isinstance(result, dict) else 0
        if processed_count:
            print(
                f"scheduler queue tick processed {processed_count} order(s)",
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:
        print(f"scheduler queue tick skipped: {exc}", file=sys.stderr, flush=True)


def main() -> None:
    from split_mcp_server.device_event_consumer import main as consumer_main

    consumer_main()


if __name__ == "__main__":
    main()
