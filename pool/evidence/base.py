"""Evidence 契约（design-v1 §4.1）：三档证据的统一返回结构。

- delivered 只在 tier=strong 时有语义；weak/none 恒 None；
- reason 必填、面向用户；
- details 保留原始读数，供 doctor 与排查使用。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Tier(str, enum.Enum):
    STRONG = "strong"
    WEAK = "weak"
    NONE = "none"


@dataclass
class Evidence:
    tier: Tier
    reason: str
    delivered: bool | None = None
    project_mismatch: bool = False
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "delivered": self.delivered if self.tier is Tier.STRONG else None,
            "reason": self.reason,
            "project_mismatch": self.project_mismatch,
            "details": self.details,
        }


def can_auto_archive(ev: Evidence) -> bool:
    """归档准入（design-v1 §4.2）：strong ∧ delivered ∧ ¬project_mismatch。"""
    return (ev.tier is Tier.STRONG and ev.delivered is True
            and not ev.project_mismatch)
