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
) -> dict[str, Any]:
    import MetaTrader5 as mt5

    if signal.action == "long":
        order_type = mt5.ORDER_TYPE_BUY
        price = ask
        sl = price - signal.stop_distance
        tp = price + signal.take_profit_distance
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = bid
        sl = price + signal.stop_distance
        tp = price - signal.take_profit_distance

    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": cfg.slippage_points,
        "magic": cfg.magic_number,
        "comment": "xauusd-trader",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

