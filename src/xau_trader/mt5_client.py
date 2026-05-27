from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover
    mt5 = None

from .config import Mt5Credentials


@dataclass
class SymbolMeta:
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    filling_mode: int
    trade_exemode: int


class Mt5Client:
    def __init__(self, creds: Mt5Credentials) -> None:
        self.creds = creds

    def connect(self) -> None:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package is not available.")
        ok = mt5.initialize(path=self.creds.path) if self.creds.path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.login(login=self.creds.login, password=self.creds.password, server=self.creds.server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def ensure_symbol(self, symbol: str) -> SymbolMeta:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Could not select symbol: {symbol}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol info unavailable: {symbol}")
        return SymbolMeta(
            point=float(info.point),
            tick_size=float(info.trade_tick_size),
            tick_value=float(info.trade_tick_value),
            contract_size=float(info.trade_contract_size),
            volume_min=float(info.volume_min),
            volume_step=float(info.volume_step),
            volume_max=float(info.volume_max),
            filling_mode=int(info.filling_mode),
            trade_exemode=int(info.trade_exemode),
        )

    def account_info(self) -> Any:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("MT5 account_info unavailable.")
        return info

    def positions_total_by_symbol(self, symbol: str) -> int:
        pos = mt5.positions_get(symbol=symbol)
        return 0 if pos is None else len(pos)

    def position_exists(self, symbol: str, ticket: int | None = None) -> bool:
        pos = mt5.positions_get(symbol=symbol)
        if not pos:
            return False
        if ticket is None or ticket <= 0:
            return True
        return any(int(p.ticket) == int(ticket) for p in pos)

    def latest_tick(self, symbol: str) -> Any:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}")
        return tick

    def copy_rates(self, symbol: str, timeframe: int, count: int = 300) -> list[Any]:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            raise RuntimeError(f"Could not read rates for {symbol}")
        return rates

    @staticmethod
    def to_utc_timestamp(epoch_seconds: int) -> datetime:
        return datetime.fromtimestamp(epoch_seconds, tz=UTC)
