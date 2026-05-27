from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class TraderState:
    last_decision_utc: str | None = None
    last_action: str | None = None
    cooldown_until_utc: str | None = None
    consecutive_errors: int = 0
    total_signals: int = 0
    total_orders_sent: int = 0
    total_orders_failed: int = 0
    total_blocks: int = 0
    total_retries: int = 0
    risk_day_utc: str | None = None
    risk_day_start_equity: float | None = None
    last_processed_bar_time_utc: str | None = None
    last_signal_bar_time_utc: str | None = None


def load_state(path: str) -> TraderState:
    p = Path(path)
    if not p.exists():
        return TraderState()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return TraderState(**raw)


def save_state(path: str, state: TraderState) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(state), ensure_ascii=True, indent=2), encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()
