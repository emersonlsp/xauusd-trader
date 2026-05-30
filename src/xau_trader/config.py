from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class SessionHours(BaseModel):
    start: str = "00:00"
    end: str = "23:59"


class RuntimeConfig(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    artifact_path: str
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 1
    max_spread_points: float = 80.0
    slippage_points: int = 30
    commission_per_lot_per_side: float = 3.0
    swap_per_lot_per_day: float = 0.0
    session_hours: SessionHours = Field(default_factory=SessionHours)
    magic_number: int = 7726001
    dry_run: bool = True
    cooldown_seconds: int = 20
    poll_interval_seconds: int = 5
    stale_data_seconds: int = 120
    feature_lookback_bars: int = 3600
    max_consecutive_errors: int = 5
    mt5_retry_attempts: int = 3
    mt5_retry_delay_seconds: int = 2
    kill_switch_path: str = "logs/KILL_SWITCH"
    state_path: str = "logs/state.json"
    decision_log_path: str = "logs/decisions.jsonl"
    execution_log_path: str = "logs/executions.jsonl"
    report_path: str = "reports/daily_summary.json"
    heartbeat_seconds: int = 30
    fallback_stop_loss_points: float = 100.0
    fallback_risk_reward_ratio: float = 1.2
    invert_signals: bool = False


class AccountConfig(BaseModel):
    name: str
    login_env: str
    password_env: str
    server_env: str
    path_env: str
    allow_live: bool = False


class Mt5Credentials(BaseModel):
    login: int
    password: str
    server: str
    path: str | None = None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_configs(account: str, runtime_path: str = "config/runtime.yaml") -> tuple[RuntimeConfig, AccountConfig, Mt5Credentials]:
    load_dotenv()
    runtime_raw = _load_yaml(Path(runtime_path))
    runtime = RuntimeConfig(**runtime_raw)

    account_path = Path("config") / "accounts" / f"{account}.yaml"
    account_raw = _load_yaml(account_path)
    account_cfg = AccountConfig(**account_raw)

    login_raw = os.getenv(account_cfg.login_env, "").strip()
    password = os.getenv(account_cfg.password_env, "").strip()
    server = os.getenv(account_cfg.server_env, "").strip()
    path = os.getenv(account_cfg.path_env, "").strip() or None
    if not login_raw or not password or not server:
        raise ValueError("Missing MT5 credentials in environment variables.")

    creds = Mt5Credentials(login=int(login_raw), password=password, server=server, path=path)
    return runtime, account_cfg, creds


