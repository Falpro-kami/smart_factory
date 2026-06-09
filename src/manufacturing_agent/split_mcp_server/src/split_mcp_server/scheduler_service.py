"""Background order scheduler service.

This service is the runtime scheduler:
- consumes DeviceEventReport for device/work-order events;
- drains submitted orders from scheduler_order_queue;
- produces WorkOrderDeliver messages through the scheduler core.
"""

from split_mcp_server.device_event_consumer import main


if __name__ == "__main__":
    main()
