from __future__ import annotations

from typing import Any

from .config import RuntimeConfig
from .types import Signal


def build_order_request(
    cfg: RuntimeConfig,
    symbol: str,
    signal: Signal,
    volume: float,
    bid: float,
    ask: float,
    filling_mode: int | None = None,
    tick_size: float = 0.01,
    trade_exemode: int | None = None,
) -> dict[str, Any]:
    import MetaTrader5 as mt5
    deviation_points = max(1, int(round(cfg.slippage_points)))
    ts = tick_size if tick_size > 0 else 0.01

    def _norm_price(v: float) -> float:
        return float(round(v / ts) * ts)

    if signal.action == "long":
        order_type = mt5.ORDER_TYPE_BUY
        price = _norm_price(ask)
        sl = _norm_price(price - signal.stop_distance)
        tp = _norm_price(price + signal.take_profit_distance)
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = _norm_price(bid)
        sl = _norm_price(price + signal.stop_distance)
        tp = _norm_price(price - signal.take_profit_distance)

    request = {
        "action": int(mt5.TRADE_ACTION_DEAL),
        "symbol": str(symbol),
        "volume": float(volume),
        "type": int(order_type),
        "price": float(price),
        "sl": float(sl),
        "tp": float(tp),
        "deviation": int(deviation_points),
        "magic": int(cfg.magic_number),
        "comment": "xauusd-trader",
        "type_time": int(mt5.ORDER_TIME_GTC),
        "type_filling": int(filling_mode) if filling_mode is not None else int(mt5.ORDER_FILLING_IOC),
    }
    return request
