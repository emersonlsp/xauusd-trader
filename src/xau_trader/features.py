from __future__ import annotations

from datetime import UTC, datetime
from statistics import mean, pstdev
from typing import Any

import numpy as np

from .market_data import MarketSnapshot


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append((alpha * v) + ((1.0 - alpha) * out[-1]))
    return out


def _build_h1_zone_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    if len(rows) < 3000:
        return {}
    h1: list[dict[str, Any]] = []
    block = 60
    for i in range(0, len(rows), block):
        chunk = rows[i : i + block]
        if len(chunk) < block:
            break
        h1.append(
            {
                "ts_open": str(chunk[0]["ts_open"]),
                "high": max(float(r["high"]) for r in chunk),
                "low": min(float(r["low"]) for r in chunk),
                "close": float(chunk[-1]["close"]),
            }
        )
    if len(h1) < 50:
        return {}
    h_high = [float(x["high"]) for x in h1]
    h_low = [float(x["low"]) for x in h1]
    tr = [h_high[i] - h_low[i] for i in range(len(h1))]
    atr14 = [mean(tr[max(0, i - 13) : i + 1]) for i in range(len(h1))]
    pivot_w = 3
    zones: list[dict[str, float]] = []
    for i in range(pivot_w, len(h1) - pivot_w):
        c_hi = h_high[i]
        c_lo = h_low[i]
        if c_hi >= max(h_high[i - pivot_w : i + pivot_w + 1]):
            width = max(1.0e-6, atr14[i] * 0.35)
            zones.append({"h1_idx": float(i), "type": 1.0, "price": c_hi})
        if c_lo <= min(h_low[i - pivot_w : i + pivot_w + 1]):
            width = max(1.0e-6, atr14[i] * 0.35)
            zones.append({"h1_idx": float(i), "type": -1.0, "price": c_lo})
    if not zones:
        return {}
    out: dict[str, dict[str, float]] = {}
    for m1_idx, r in enumerate(rows):
        h_idx = m1_idx // block
        c = float(r["close"])
        prev_c = float(rows[m1_idx - 1]["close"]) if m1_idx > 0 else c
        supports = [z for z in zones if z["type"] < 0 and int(z["h1_idx"]) <= h_idx]
        resists = [z for z in zones if z["type"] > 0 and int(z["h1_idx"]) <= h_idx]
        sup = max((z for z in supports if z["price"] <= c), key=lambda z: z["price"], default=None)
        res = min((z for z in resists if z["price"] >= c), key=lambda z: z["price"], default=None)
        h1_atr = atr14[min(h_idx, len(atr14) - 1)]
        near_band = max(1.0e-6, h1_atr * 0.20)
        sup_p = float(sup["price"]) if sup is not None else c
        res_p = float(res["price"]) if res is not None else c
        sup_dist = (c - sup_p) / max(1.0e-6, h1_atr) if sup is not None else 0.0
        res_dist = (res_p - c) / max(1.0e-6, h1_atr) if res is not None else 0.0
        zone_between = 1.0 if (sup is not None and res is not None and c >= sup_p and c <= res_p) else 0.0
        near_sup = 1.0 if sup is not None and abs(c - sup_p) <= near_band else 0.0
        near_res = 1.0 if res is not None and abs(c - res_p) <= near_band else 0.0
        break_sup = 1.0 if sup is not None and prev_c >= sup_p and c < sup_p else 0.0
        reclaim_sup = 1.0 if sup is not None and prev_c < sup_p and c >= sup_p else 0.0
        break_res = 1.0 if res is not None and prev_c <= res_p and c > res_p else 0.0
        reject_res = 1.0 if res is not None and prev_c > res_p and c <= res_p else 0.0
        out[str(r["ts_open"])] = {
            "zone_support_dist_atr": float(sup_dist),
            "zone_resist_dist_atr": float(res_dist),
            "zone_between_sr": float(zone_between),
            "zone_near_support": float(near_sup),
            "zone_near_resist": float(near_res),
            "zone_break_support": float(break_sup),
            "zone_reclaim_support": float(reclaim_sup),
            "zone_break_resist": float(break_res),
            "zone_reject_resist": float(reject_res),
        }
    return out


def build_features(snapshot: MarketSnapshot) -> dict[str, float]:
    n = snapshot.closes.size
    if n < 120:
        raise ValueError("Not enough bars to build training-parity features.")

    closes = snapshot.closes.tolist()
    highs = snapshot.highs.tolist()
    lows = snapshot.lows.tolist()
    vols = snapshot.volumes.tolist()
    times = snapshot.bar_times_epoch.tolist()
    rows: list[dict[str, Any]] = []
    for i in range(n):
        ts = datetime.fromtimestamp(int(times[i]), tz=UTC).isoformat()
        rows.append({"ts_open": ts, "close": closes[i], "high": highs[i], "low": lows[i], "tick_volume": vols[i]})

    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    i = n - 1
    c = float(closes[i])
    ret_1 = (c / closes[i - 1]) - 1.0
    ret_5 = (c / closes[i - 5]) - 1.0
    ret_15 = (c / closes[i - 15]) - 1.0
    ret_60 = (c / closes[i - 60]) - 1.0
    atr14 = mean([highs[j] - lows[j] for j in range(i - 13, i + 1)])
    atr_pct = (atr14 / c) if c > 0 else 0.0
    vol_window = [((closes[j] / closes[j - 1]) - 1.0) for j in range(i - 19, i + 1)]
    rv20 = pstdev(vol_window) if len(vol_window) > 1 else 0.0
    vol_mean20 = mean(vols[i - 19 : i + 1]) if i >= 19 else 0.0
    vol_ratio = (vols[i] / vol_mean20) if vol_mean20 > 0 else 1.0
    slope21 = (ema21[i] / ema21[i - 5]) - 1.0 if ema21[i - 5] != 0 else 0.0
    slope50 = (ema50[i] / ema50[i - 10]) - 1.0 if ema50[i - 10] != 0 else 0.0

    mlofi_vals = [
        ret_1,
        ret_5,
        ret_15,
        ret_60,
        atr_pct,
        rv20,
        slope21,
        slope50,
        vol_ratio - 1.0,
        (highs[i] - lows[i]) / c if c > 0 else 0.0,
    ]
    zone_map = _build_h1_zone_map(rows)
    z = zone_map.get(rows[i]["ts_open"], {})
    return {
        "mlofi_l1": float(mlofi_vals[0]),
        "mlofi_l2": float(mlofi_vals[1]),
        "mlofi_l3": float(mlofi_vals[2]),
        "mlofi_l4": float(mlofi_vals[3]),
        "mlofi_l5": float(mlofi_vals[4]),
        "mlofi_l6": float(mlofi_vals[5]),
        "mlofi_l7": float(mlofi_vals[6]),
        "mlofi_l8": float(mlofi_vals[7]),
        "mlofi_l9": float(mlofi_vals[8]),
        "mlofi_l10": float(mlofi_vals[9]),
        "mlofi_score": float(sum(mlofi_vals) / len(mlofi_vals)),
        "spread": float(snapshot.spread_points),
        "zone_support_dist_atr": float(z.get("zone_support_dist_atr", 0.0)),
        "zone_resist_dist_atr": float(z.get("zone_resist_dist_atr", 0.0)),
        "zone_between_sr": float(z.get("zone_between_sr", 0.0)),
        "zone_near_support": float(z.get("zone_near_support", 0.0)),
        "zone_near_resist": float(z.get("zone_near_resist", 0.0)),
        "zone_break_support": float(z.get("zone_break_support", 0.0)),
        "zone_reclaim_support": float(z.get("zone_reclaim_support", 0.0)),
        "zone_break_resist": float(z.get("zone_break_resist", 0.0)),
        "zone_reject_resist": float(z.get("zone_reject_resist", 0.0)),
        "last_price": c,
        "range_14": atr14,
    }


