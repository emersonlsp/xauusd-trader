from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Action = Literal["long", "short", "hold"]


@dataclass
class Signal:
    action: Action
    confidence: float
    stop_distance: float
    take_profit_distance: float
    meta: dict[str, Any]

