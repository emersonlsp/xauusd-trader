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


def _timeframe_minutes(timeframe: str) -> int:
    mapping = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}
    return mapping.get(timeframe, 1)


def _send_order_with_fallbacks(
    runtime: RuntimeConfig,
    state: TraderState,
    base_request: dict,
) -> tuple[Any, dict, str, Any]:
    import MetaTrader5 as mt5

    def _safe_order_check(req: dict):
        try:
            return mt5.order_check(req)
        except TypeError:
            return mt5.order_check(request=req)

    def _safe_order_send(req: dict):
        try:
            return mt5.order_send(req)
        except TypeError:
            return mt5.order_send(request=req)

    filling_candidates = [int(mt5.ORDER_FILLING_IOC), int(mt5.ORDER_FILLING_FOK), int(mt5.ORDER_FILLING_RETURN)]
    original_filling = int(base_request.get("type_filling", filling_candidates[0]))
    ordered = [original_filling] + [f for f in filling_candidates if f != original_filling]

    last_error = ""
    last_check = None
    last_result = None
    last_request = dict(base_request)
    for fill in ordered:
        req = dict(base_request)
        req["type_filling"] = int(fill)
        check = _with_retry(runtime, state, _safe_order_check, req)
        last_check = check
        if check is None:
            last_error = str(mt5.last_error())
            last_request = req
            continue
        check_ret = int(getattr(check, "retcode", 0))
        if check_ret not in {0, mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            last_request = req
            # Keep trying other filling policies when check says invalid/fill issues.
            if check_ret in {mt5.TRADE_RETCODE_INVALID, mt5.TRADE_RETCODE_INVALID_FILL}:
                continue
            return None, req, f"order_check_retcode={check_ret} comment={getattr(check, 'comment', '')}", check
        result = _with_retry(runtime, state, _safe_order_send, req)
        if result is None:
            last_error = str(mt5.last_error())
            last_request = req
            continue
        last_result = result
        last_request = req
        ret = int(getattr(result, "retcode", 0))
        if ret in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            return result, req, last_error, check
        # Try another filling mode when broker says request is invalid.
        if ret == mt5.TRADE_RETCODE_INVALID:
            continue
        return result, req, last_error, check
    return last_result, last_request, last_error, last_check


def _to_dict_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "_asdict"):
        out = {}
        for k, v in obj._asdict().items():
            if hasattr(v, "_asdict"):
                out[k] = v._asdict()
            else:
                out[k] = v
        return out
    return str(obj)


def _apply_position_sltp(runtime: RuntimeConfig, state: TraderState, symbol: str, position_ticket: int, sl: float, tp: float) -> tuple[bool, str]:
    def _safe_order_check(req: dict):
        try:
            return mt5.order_check(req)
        except TypeError:
            return mt5.order_check(request=req)

    def _safe_order_send(req: dict):
        try:
            return mt5.order_send(req)
        except TypeError:
            return mt5.order_send(request=req)

    pos = None
    try:
        all_pos = mt5.positions_get(symbol=symbol)
    except Exception:
        all_pos = None
    if all_pos:
        for p in all_pos:
            if int(getattr(p, "ticket", 0)) == int(position_ticket):
                pos = p
                break
        if pos is None:
            pos = max(all_pos, key=lambda p: int(getattr(p, "time", 0)))

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, "symbol info/tick unavailable for SLTP"
    ts = float(getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.01) or 0.01)

    def _norm_price(v: float) -> float:
        return float(round(float(v) / ts) * ts)

    sl_n = _norm_price(sl)
    tp_n = _norm_price(tp)

    # Validate side constraints against live prices to avoid broker invalid-request.
    if pos is not None:
        ptype = int(getattr(pos, "type", -1))
        if ptype == int(mt5.POSITION_TYPE_BUY):
            if not (sl_n < float(tick.bid) and tp_n > float(tick.bid)):
                return False, f"invalid BUY SLTP bounds: bid={float(tick.bid)} sl={sl_n} tp={tp_n}"
        elif ptype == int(mt5.POSITION_TYPE_SELL):
            if not (sl_n > float(tick.ask) and tp_n < float(tick.ask)):
                return False, f"invalid SELL SLTP bounds: ask={float(tick.ask)} sl={sl_n} tp={tp_n}"

    req = {
        "action": int(mt5.TRADE_ACTION_SLTP),
        "symbol": str(symbol),
        "position": int(position_ticket),
        "sl": float(sl_n),
        "tp": float(tp_n),
    }
    check = _with_retry(runtime, state, _safe_order_check, req)
    if check is not None:
        check_ret = int(getattr(check, "retcode", 0))
        if check_ret not in {0, mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            return False, f"order_check retcode={check_ret} comment={str(getattr(check, 'comment', ''))}"
    result = _with_retry(runtime, state, _safe_order_send, req)
    if result is None:
        return False, f"order_send None: {mt5.last_error()}"
    ok = int(result.retcode) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
    return ok, f"retcode={int(result.retcode)} comment={str(result.comment)}"


def _resolve_position_ticket(symbol: str, fallback_ticket: int) -> int:
    try:
        pos = mt5.positions_get(symbol=symbol)
    except Exception:
        pos = None
    if pos:
        # Prefer latest opened position for this symbol.
        latest = max(pos, key=lambda p: int(getattr(p, "time", 0)))
        return int(getattr(latest, "ticket", fallback_ticket))
    return int(fallback_ticket)


def run(runtime: RuntimeConfig, client: Mt5Client, risk_override: float | None = None, reset_state: bool = False) -> None:
    strategy = StrategyAdapter(runtime.artifact_path)
    state = TraderState() if reset_state else load_state(runtime.state_path)
    art_runtime = strategy.runtime_from_artifact()
    runtime.symbol = str(art_runtime.get("symbol") or runtime.symbol)
    runtime.timeframe = str(art_runtime.get("timeframe") or runtime.timeframe)
    # Keep local runtime risk as the default operational control.
    # Artifact risk can still be used explicitly via CLI override if desired.
    runtime.risk_per_trade_pct = float(runtime.risk_per_trade_pct)
    runtime.max_open_positions = int(art_runtime.get("max_open_positions") or runtime.max_open_positions)
    runtime.slippage_points = int(float(art_runtime.get("slippage_points") or runtime.slippage_points))
    runtime.commission_per_lot_per_side = float(
        art_runtime.get("commission_per_lot_per_side") or runtime.commission_per_lot_per_side
    )
    runtime.swap_per_lot_per_day = float(art_runtime.get("swap_per_lot_per_day") or runtime.swap_per_lot_per_day)

    decision_rules = strategy.decision_rules
    decision_on_bar_close = bool(decision_rules.get("decision_on_bar_close", True))
    signal_interval_bars = int(decision_rules.get("signal_interval_bars", 1))
    warmup_bars_min = int(decision_rules.get("warmup_bars_min", 120))

    symbol_meta = client.ensure_symbol(runtime.symbol)
    constraints = strategy.symbol_constraints
    if constraints:
        symbol_meta.tick_size = float(constraints.get("tick_size", symbol_meta.tick_size))
        symbol_meta.tick_value = float(constraints.get("tick_value", symbol_meta.tick_value))
        symbol_meta.contract_size = float(constraints.get("contract_size", symbol_meta.contract_size))
        symbol_meta.volume_min = float(constraints.get("min_lot", symbol_meta.volume_min))
        symbol_meta.volume_step = float(constraints.get("lot_step", symbol_meta.volume_step))
        symbol_meta.volume_max = float(constraints.get("max_lot", symbol_meta.volume_max))

    risk_pct = risk_override if risk_override is not None else runtime.risk_per_trade_pct
    append_jsonl(
        runtime.decision_log_path,
        {
            "event": "startup",
            "symbol": runtime.symbol,
            "timeframe": runtime.timeframe,
            "artifact_path": runtime.artifact_path,
            "invert_signals": runtime.invert_signals,
            "risk_per_trade_pct": risk_pct,
        },
    )
    last_heartbeat_ts = 0.0
    while True:
        if kill_switch_engaged(runtime):
            append_jsonl(runtime.decision_log_path, {"event": "shutdown", "reason_code": rc.KILL_SWITCH})
            break
        try:
            snapshot = _with_retry(
                runtime,
                state,
                load_snapshot,
                client,
                runtime.symbol,
                runtime.timeframe,
                symbol_meta.point,
                max(800, warmup_bars_min),
            )
            acc = _with_retry(runtime, state, client.account_info)
            now_ts = time.time()
            if now_ts - last_heartbeat_ts >= runtime.heartbeat_seconds:
                heartbeat_payload = {
                    "event": "heartbeat",
                    "symbol": runtime.symbol,
                    "timeframe": runtime.timeframe,
                    "equity": float(acc.equity),
                    "balance": float(acc.balance),
                    "signals": state.total_signals,
                    "orders_sent": state.total_orders_sent,
                    "orders_failed": state.total_orders_failed,
                    "blocks": state.total_blocks,
                }
                append_jsonl(runtime.decision_log_path, heartbeat_payload)
                print(
                    f"[HEARTBEAT] {runtime.symbol} {runtime.timeframe} "
                    f"eq={float(acc.equity):.2f} bal={float(acc.balance):.2f} "
                    f"signals={state.total_signals} orders={state.total_orders_sent} blocks={state.total_blocks}",
                    flush=True,
                )
                last_heartbeat_ts = now_ts
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

            current_bar_iso = snapshot.last_bar_time_utc.isoformat()
            if decision_on_bar_close and state.last_processed_bar_time_utc == current_bar_iso:
                state.total_blocks += 1
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.BAR_ALREADY_PROCESSED})
                time.sleep(runtime.poll_interval_seconds)
                continue
            if state.last_signal_bar_time_utc and signal_interval_bars > 1:
                last_signal_bar = datetime.fromisoformat(state.last_signal_bar_time_utc)
                bars_since = int(
                    (snapshot.last_bar_time_utc - last_signal_bar).total_seconds()
                    // (_timeframe_minutes(runtime.timeframe) * 60)
                )
                if bars_since < signal_interval_bars:
                    state.total_blocks += 1
                    append_jsonl(
                        runtime.decision_log_path,
                        {
                            "event": "blocked",
                            "reason_code": rc.SIGNAL_INTERVAL_WAIT,
                            "bars_since_last_signal": bars_since,
                            "signal_interval_bars": signal_interval_bars,
                        },
                    )
                    time.sleep(runtime.poll_interval_seconds)
                    continue

            features = build_features(snapshot)
            signal = strategy.predict(
                features,
                point=symbol_meta.point,
                fallback_sl_points=runtime.fallback_stop_loss_points,
                fallback_rr=runtime.fallback_risk_reward_ratio,
            )
            if runtime.invert_signals:
                if signal.action == "long":
                    signal.action = "short"
                elif signal.action == "short":
                    signal.action = "long"
            state.total_signals += 1
            state.last_processed_bar_time_utc = current_bar_iso
            append_jsonl(
                runtime.decision_log_path,
                {
                    "event": "signal",
                    "action": signal.action,
                    "confidence": signal.confidence,
                    "pred_class": signal.meta.get("pred_class"),
                    "probs": signal.meta.get("probs"),
                    "invert_signals": runtime.invert_signals,
                    "stop_distance_price": float(signal.stop_distance),
                    "take_profit_distance_price": float(signal.take_profit_distance),
                },
            )
            if signal.action == "hold":
                append_jsonl(runtime.decision_log_path, {"event": "blocked", "reason_code": rc.SIGNAL_HOLD})
                time.sleep(runtime.poll_interval_seconds)
                continue

            volume = compute_volume_by_risk(
                equity=float(acc.equity),
                risk_pct=risk_pct,
                stop_distance_price=signal.stop_distance,
                meta=symbol_meta,
            )
            if volume <= 0:
                state.total_blocks += 1
                append_jsonl(
                    runtime.decision_log_path,
                    {
                        "event": "blocked",
                        "reason_code": rc.RISK_BELOW_MIN_LOT,
                        "equity": float(acc.equity),
                        "risk_pct": risk_pct,
                        "stop_distance_price": float(signal.stop_distance),
                        "volume_min": float(symbol_meta.volume_min),
                    },
                )
                time.sleep(runtime.poll_interval_seconds)
                continue

            request = build_order_request(
                cfg=runtime,
                symbol=runtime.symbol,
                signal=signal,
                volume=volume,
                bid=snapshot.bid,
                ask=snapshot.ask,
                filling_mode=symbol_meta.filling_mode,
                tick_size=symbol_meta.tick_size,
                trade_exemode=symbol_meta.trade_exemode,
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
                # Proven broker-compatible pattern: open DEAL first without SL/TP, then apply SL/TP.
                open_request = dict(request)
                open_request["sl"] = 0.0
                open_request["tp"] = 0.0
                open_request["type_filling"] = int(mt5.ORDER_FILLING_IOC)

                result, used_request, last_error, check_result = _send_order_with_fallbacks(runtime, state, open_request)
                state.total_orders_sent += 1
                if result is None:
                    state.total_orders_failed += 1
                    append_jsonl(
                        runtime.execution_log_path,
                        {
                            "event": "execution",
                            "reason_code": rc.ORDER_SEND_NULL_RESULT,
                            "request": used_request,
                            "mt5_last_error": last_error,
                            "order_check_retcode": (
                                None if check_result is None else int(getattr(check_result, "retcode", 0))
                            ),
                            "order_check_comment": (
                                None if check_result is None else str(getattr(check_result, "comment", ""))
                            ),
                            "order_check_dump": _to_dict_safe(check_result),
                        },
                    )
                    time.sleep(runtime.poll_interval_seconds)
                    continue
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
                    if confirmed_open:
                        pos_ticket = _resolve_position_ticket(runtime.symbol, int(getattr(result, "order", 0)))
                        if pos_ticket > 0:
                            sltp_ok, sltp_msg = _apply_position_sltp(
                                runtime,
                                state,
                                runtime.symbol,
                                pos_ticket,
                                float(request["sl"]),
                                float(request["tp"]),
                            )
                            append_jsonl(
                                runtime.execution_log_path,
                                {
                                    "event": "post_open_sltp",
                                    "order_ticket": pos_ticket,
                                    "sltp_applied": sltp_ok,
                                    "details": sltp_msg,
                                    "sl": float(request["sl"]),
                                    "tp": float(request["tp"]),
                                },
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
                        "request": used_request,
                        "retcode": int(result.retcode),
                        "comment": str(result.comment),
                        "order_check_dump": _to_dict_safe(check_result),
                        "order_ticket": int(getattr(result, "order", 0)),
                        "deal_ticket": int(getattr(result, "deal", 0)),
                        "confirmed_open": confirmed_open,
                    },
                )

            state.last_decision_utc = utc_now_iso()
            state.last_action = signal.action
            state.last_signal_bar_time_utc = current_bar_iso
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
