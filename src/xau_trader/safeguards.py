from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path

from .config import RuntimeConfig
from .market_data import MarketSnapshot


def in_session(cfg: RuntimeConfig, now_utc: datetime) -> bool:
    sh = cfg.session_hours
    start = time.fromisoformat(sh.start)
    end = time.fromisoformat(sh.end)
    now_t = now_utc.time()
    if start <= end:
        return start <= now_t <= end
    return now_t >= start or now_t <= end


def stale_data(cfg: RuntimeConfig, snapshot: MarketSnapshot) -> bool:
    delta = (snapshot.now_utc - snapshot.last_bar_time_utc).total_seconds()
    return delta > cfg.stale_data_seconds


def kill_switch_engaged(cfg: RuntimeConfig) -> bool:
    return Path(cfg.kill_switch_path).exists()

