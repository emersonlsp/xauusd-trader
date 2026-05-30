from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_configs
from .validate_artifact import validate_artifact


def cli() -> None:
    parser = argparse.ArgumentParser(description="XAUUSD MT5 execution trader")
    parser.add_argument("--account", required=True, choices=["demo", "live"])
    parser.add_argument("--runtime-config", default="config/runtime.yaml")
    parser.add_argument("--risk-per-trade-pct", type=float, default=None)
    parser.add_argument("--reset-state", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Only validate artifact contract and exit")
    parser.add_argument(
        "--strict-unsup-full",
        action="store_true",
        help="Fail validation when unsupervised gate is enabled without full cluster payload",
    )
    args = parser.parse_args()

    runtime, account_cfg, creds = load_configs(args.account, runtime_path=args.runtime_config)
    if args.account == "live" and not account_cfg.allow_live:
        raise RuntimeError("Live account profile is not allowed.")

    issues, warnings, diag = validate_artifact(Path(runtime.artifact_path), strict_unsup_full=bool(args.strict_unsup_full))
    print(f"[artifact-check] artifact={runtime.artifact_path}")
    print(
        "[artifact-check] "
        f"symbol={diag.get('symbol')} timeframe={diag.get('timeframe')} features={diag.get('features')} "
        f"target_classes={diag.get('target_classes')} unsup={diag.get('unsup_enabled')} mode={diag.get('unsup_mode')}"
    )
    for w in warnings:
        print(f"[artifact-check] WARN: {w}")
    if issues:
        for i in issues:
            print(f"[artifact-check] FAIL: {i}")
        raise RuntimeError("Artifact validation failed. Trader execution blocked.")

    print("[artifact-check] PASS")
    if args.validate_only:
        return

    from .mt5_client import Mt5Client
    from .runner import run

    client = Mt5Client(creds)
    client.connect()
    try:
        run(
            runtime=runtime,
            client=client,
            risk_override=args.risk_per_trade_pct,
            reset_state=args.reset_state,
        )
    finally:
        client.shutdown()


if __name__ == "__main__":
    cli()
