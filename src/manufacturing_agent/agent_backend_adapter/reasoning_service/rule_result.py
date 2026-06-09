from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def normalized_identity_tokens(values: list[Any]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        tokens.add(normalize_text(text))
        if ":" in text:
            tokens.add(normalize_text(text.split(":", 1)[1]))
    return {token for token in tokens if token}


@dataclass
class RuleResult:
    rule_id: str
    status: str
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleId": self.rule_id,
            "status": self.status,
            "message": self.message,
            **self.metrics,
        }
