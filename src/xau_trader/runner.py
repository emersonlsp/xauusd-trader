from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import MetaTrader5 as mt5

from .config import RuntimeConfig
from .execution import build_order_request
from .features import build_features
from .market_data import load_snapshot
from .mt5_client import Mt5Client
from . import reason_codes as rc
from .reporting import append_jsonl, write_daily_summary
from .risk import compute_volume_by_risk
from .safeguards import in_session, kill_switch_engaged, stale_data
from .state_store import TraderState, load_state, save_state, utc_now_iso
from .strategy_adapter import StrategyAdapter


def _is_in_cooldown(state: TraderState) -> bool:
    if not state.cooldown_until_utc:
        return False
    try:
        until = datetime.fromisoformat(state.cooldown_until_utc)
        return datetime.now(tz=UTC) < until
    except ValueError:
        return False


def _with_retry(runtime: RuntimeConfig, state: TraderState, fn, *args, **kwargs):
    last_exc = None
    for attempt in range(1, runtime.mt5_retry_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < runtime.mt5_retry_attempts:
                state.total_retries += 1
                time.sleep(runtime.mt5_retry_delay_seconds)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry wrapper failed without exception.")


def run(runtime: RuntimeConfig, client: Mt5Client, risk_override: float | None = None) -> None:
    strategy = StrategyAdapter(runtime.artifact_path)
    state = load_state(runtime.state_path)
    symbol_meta = client.ensure_symbol(runtime.symbol)

    risk_pct = risk_override if risk_override is not None else runtime.risk_per_trade_pct
    while True:
        if kill_switch_engaged(runtime):
            append_jsonl(runtime.decision_log_path, {"event": "shutdown", "reason_code": rc.KILL_SWITCH})
            break
        try:
            snapshot = _with_retry(runtime, state, load_snapshot, client, runtime.symbol, runtime.timeframe, symbol_meta.point)
            acc = _with_retry(runtime, state, client.account_info)
            today_utc = datetime.now(tz=UTC).date().isoformat()
            if state.risk_day_utc != today_utc or state.risk_day_start_equity is None:
                state.risk_day_utc = today_utc
                state.risk_day_start_equity = float(acc.equity)

            dd_limit_equity = float(state.risk_day_start_equity) * (1.0 - runtime.max_daily_loss_pct)
            if float(acc.equity) <= dd_limit_equity:
                append_jsonl(
                    runtime.decision_log_path,
                    {
                        "event": "shutdown",
                        "reason_code": rc.MAX_DRAWDOWN_REACHED,
                        "equity": float(acc.equity),
                        "risk_day_start_equity": float(state.risk_day_start_equity),
                        "max_daily_loss_pct": runtime.max_daily_loss_pct,
                    },
                )
                save_state(runtime.state_path, state)
                break

            if stale_data(runtime, snapshot):
                state.total_blocks += 1
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.STALE_DATA})
                time.sleep(runtime.poll_interval_seconds)
                continue
            if snapshot.spread_points > runtime.max_spread_points:
                state.total_blocks += 1
                append_jsonl(
                    runtime.decision_log_path,
                    {"event": "blocked", "reason_code": rc.SPREAD_TOO_HIGH, "spread_points": snapshot.spread_points},
                )
                time.sleep(runtime.poll_interval_seconds)
                continue
            if not in_session(runtime, snapshot.now_utc):
                state.total_blocks += 1
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.OUT_OF_SESSION})
                time.sleep(runtime.poll_interval_seconds)
                continue
            if _is_in_cooldown(state):
                state.total_blocks += 1
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.COOLDOWN_ACTIVE})
                time.sleep(runtime.poll_interval_seconds)
                continue
            if _with_retry(runtime, state, client.positions_total_by_symbol, runtime.symbol) >= runtime.max_open_positions:
                state.total_blocks += 1
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.POSITION_LOCK})
                time.sleep(runtime.poll_interval_seconds)
                continue

            features = build_features(snapshot)
            signal = strategy.predict(features)
            state.total_signals += 1
            if signal.action == "hold":
                append_jsonl(
                    runtime.decision_log_path,
                    {"event": "signal", "reason_code": rc.SIGNAL_HOLD, "action": "hold", "confidence": signal.confidence},
                )
                time.sleep(runtime.poll_interval_seconds)
                continue

            volume = compute_volume_by_risk(
                equity=float(acc.equity),
                risk_pct=risk_pct,
                stop_distance_price=signal.stop_distance,
                meta=symbol_meta,
            )

            request = build_order_request(
                cfg=runtime,
                symbol=runtime.symbol,
                signal=signal,
                volume=volume,
                bid=snapshot.bid,
                ask=snapshot.ask,
            )

            if runtime.dry_run:
                state.total_orders_sent += 1
                append_jsonl(
                    runtime.execution_log_path,
                    {
                        "event": "execution",
                        "reason_code": rc.DRY_RUN_ORDER,
                        "request": request,
                        "action": signal.action,
                        "confidence": signal.confidence,
                    },
                )
            else:
                result = _with_retry(runtime, state, mt5.order_send, request)
                state.total_orders_sent += 1
                order_ok = int(result.retcode) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
                confirmed_open = False
                if order_ok:
                    time.sleep(1.0)
                    confirmed_open = _with_retry(
                        runtime,
                        state,
                        client.position_exists,
                        runtime.symbol,
                        int(getattr(result, "order", 0)),
                    )
                if not order_ok:
                    state.total_orders_failed += 1
                if order_ok and not confirmed_open:
                    state.total_orders_failed += 1
                append_jsonl(
                    runtime.execution_log_path,
                    {
                        "event": "execution",
                        "reason_code": (
                            rc.ORDER_SENT
                            if order_ok and confirmed_open
                            else rc.ORDER_NOT_CONFIRMED_OPEN
                            if order_ok
                            else rc.ORDER_REJECTED
                        ),
                        "request": request,
                        "retcode": int(result.retcode),
                        "comment": str(result.comment),
                        "order_ticket": int(getattr(result, "order", 0)),
                        "deal_ticket": int(getattr(result, "deal", 0)),
                        "confirmed_open": confirmed_open,
                    },
                )

            state.last_decision_utc = utc_now_iso()
            state.last_action = signal.action
            state.cooldown_until_utc = (datetime.now(tz=UTC) + timedelta(seconds=runtime.cooldown_seconds)).isoformat()
            state.consecutive_errors = 0
            save_state(runtime.state_path, state)

            write_daily_summary(
                runtime.report_path,
                {
                    "risk_per_trade_pct": risk_pct,
                    "last_action": state.last_action,
                    "last_decision_utc": state.last_decision_utc,
                    "equity": float(acc.equity),
                    "balance": float(acc.balance),
                    "total_signals": state.total_signals,
                    "total_orders_sent": state.total_orders_sent,
                    "total_orders_failed": state.total_orders_failed,
                    "total_blocks": state.total_blocks,
                    "total_retries": state.total_retries,
                },
            )
            time.sleep(runtime.poll_interval_seconds)

        except KeyboardInterrupt:
            append_jsonl(runtime.decision_log_path, {"event": "shutdown", "reason_code": rc.KEYBOARD_INTERRUPT})
            break
        except Exception as exc:
            state.consecutive_errors += 1
            save_state(runtime.state_path, state)
            append_jsonl(
                runtime.decision_log_path,
                {
                    "event": "error",
                    "reason_code": rc.RUNTIME_ERROR,
                    "error": str(exc),
                    "consecutive_errors": state.consecutive_errors,
                },
            )
            if state.consecutive_errors >= runtime.max_consecutive_errors:
                append_jsonl(runtime.decision_log_path, {"event": "shutdown", "reason_code": rc.MAX_ERRORS_REACHED})
                break
            time.sleep(runtime.poll_interval_seconds)
