from __future__ import annotations

import argparse

from .config import load_configs
from .mt5_client import Mt5Client
from .runner import run


def cli() -> None:
    parser = argparse.ArgumentParser(description="XAUUSD MT5 execution trader")
    parser.add_argument("--account", required=True, choices=["demo", "live"])
    parser.add_argument("--runtime-config", default="config/runtime.yaml")
    parser.add_argument("--risk-per-trade-pct", type=float, default=None)
    args = parser.parse_args()

    runtime, account_cfg, creds = load_configs(args.account, runtime_path=args.runtime_config)
    if args.account == "live" and not account_cfg.allow_live:
        raise RuntimeError("Live account profile is not allowed.")

    client = Mt5Client(creds)
    client.connect()
    try:
        run(runtime=runtime, client=client, risk_override=args.risk_per_trade_pct)
    finally:
        client.shutdown()


if __name__ == "__main__":
    cli()

