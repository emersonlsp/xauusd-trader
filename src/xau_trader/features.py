from __future__ import annotations

import numpy as np

from .market_data import MarketSnapshot


def _safe_std(values: np.ndarray) -> float:
    if values.size < 2:
        return 0.0
    return float(np.std(values))


def build_features(snapshot: MarketSnapshot) -> dict[str, float]:
    closes = snapshot.closes
    if closes.size < 30:
        raise ValueError("Not enough bars to build features.")

    rets = np.diff(closes) / closes[:-1]
    momentum_5 = float((closes[-1] / closes[-6]) - 1.0) if closes.size >= 6 else 0.0
    momentum_20 = float((closes[-1] / closes[-21]) - 1.0) if closes.size >= 21 else 0.0
    vol_20 = _safe_std(rets[-20:]) if rets.size >= 20 else _safe_std(rets)
    range_14 = float(np.mean(snapshot.highs[-14:] - snapshot.lows[-14:])) if closes.size >= 14 else 0.0
    return {
        "momentum_5": momentum_5,
        "momentum_20": momentum_20,
        "vol_20": vol_20,
        "range_14": range_14,
        "spread_points": snapshot.spread_points,
    }

