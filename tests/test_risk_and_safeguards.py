from datetime import UTC, datetime

from xau_trader.config import RuntimeConfig
from xau_trader.mt5_client import SymbolMeta
from xau_trader.risk import compute_volume_by_risk, normalize_volume
from xau_trader.safeguards import in_session


def test_normalize_volume_respects_bounds_and_step() -> None:
    meta = SymbolMeta(
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=2.0,
    )
    assert normalize_volume(0.005, meta) == 0.01
    assert normalize_volume(0.237, meta) == 0.23
    assert normalize_volume(10.0, meta) == 2.0


def test_compute_volume_by_risk_positive() -> None:
    meta = SymbolMeta(
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        contract_size=100.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
    )
    vol = compute_volume_by_risk(equity=1000.0, risk_pct=0.005, stop_distance_price=1.0, meta=meta)
    assert vol > 0.0


def test_in_session_true_for_full_day_window() -> None:
    cfg = RuntimeConfig(
        symbol="XAUUSD",
        timeframe="M1",
        artifact_path="artifacts/trader/combined_trader_artifact.json",
    )
    now = datetime.now(tz=UTC)
    assert in_session(cfg, now) is True

