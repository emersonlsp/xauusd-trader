from __future__ import annotations

import math

from .mt5_client import SymbolMeta


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step


def normalize_volume(volume: float, meta: SymbolMeta) -> float:
    vol = max(meta.volume_min, min(meta.volume_max, volume))
    vol = _floor_to_step(vol, meta.volume_step)
    return round(max(meta.volume_min, min(meta.volume_max, vol)), 6)


def compute_volume_by_risk(
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    meta: SymbolMeta,
) -> float:
    if stop_distance_price <= 0:
        return 0.0

    risk_amount = equity * risk_pct
    value_per_price_unit = meta.tick_value / meta.tick_size
    loss_per_lot = stop_distance_price * value_per_price_unit
    if loss_per_lot <= 0:
        return 0.0
    raw_lots = risk_amount / loss_per_lot
    if raw_lots < meta.volume_min:
        # Respect risk cap: do not force broker minimum lot if it would exceed allowed risk.
        return 0.0
    return normalize_volume(raw_lots, meta)
