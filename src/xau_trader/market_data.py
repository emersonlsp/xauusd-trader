from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from .mt5_client import Mt5Client


@dataclass
class MarketSnapshot:
    now_utc: datetime
    bid: float
    ask: float
    spread_points: float
    closes: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    volumes: np.ndarray
    last_bar_time_utc: datetime


def timeframe_to_mt5_code(timeframe: str) -> int:
    import MetaTrader5 as mt5

    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def load_snapshot(client: Mt5Client, symbol: str, timeframe: str, point: float, bars: int = 300) -> MarketSnapshot:
    tick = client.latest_tick(symbol)
    rates = client.copy_rates(symbol, timeframe_to_mt5_code(timeframe), count=bars)
    closes = np.array([float(r["close"]) for r in rates], dtype=np.float64)
    highs = np.array([float(r["high"]) for r in rates], dtype=np.float64)
    lows = np.array([float(r["low"]) for r in rates], dtype=np.float64)
    volumes = np.array([float(r["tick_volume"]) for r in rates], dtype=np.float64)
    last_bar_time = int(rates[-1]["time"])
    spread_points = (float(tick.ask) - float(tick.bid)) / point
    return MarketSnapshot(
        now_utc=datetime.now(tz=UTC),
        bid=float(tick.bid),
        ask=float(tick.ask),
        spread_points=float(spread_points),
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        last_bar_time_utc=client.to_utc_timestamp(last_bar_time),
    )

