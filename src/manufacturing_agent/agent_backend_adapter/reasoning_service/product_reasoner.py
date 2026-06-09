from __future__ import annotations

from typing import Any


PRODUCT_PROCESS_RULE: dict[str, Any] = {
    "id": "product-process",
    "type": "产品工艺推理",
    "purpose": "根据产品找到工艺流程和工艺步骤。",
    "condition": "Product 通过 HAS_STEP 关联 Process、ProcessInstance 或 AssemblyStep。",
    "conclusion": "产品可展开为有序工艺流程，作为工单拆分的依据。",
    "example": "产品 -> 工艺流程 -> 工艺步骤",
    "source": "product",
    "target": "process",
}
