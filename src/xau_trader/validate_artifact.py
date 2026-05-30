from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any


def _as_bool(v: Any) -> bool:
    return bool(v)


def _append_issue(issues: list[str], condition: bool, message: str) -> None:
    if condition:
        issues.append(message)


def _append_warn(warnings: list[str], condition: bool, message: str) -> None:
    if condition:
        warnings.append(message)


def validate_artifact(path: Path, strict_unsup_full: bool = False) -> tuple[list[str], list[str], dict[str, Any]]:
    issues: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return [f"artifact_not_found: {path}"], warnings, {}

    raw = json.loads(path.read_text(encoding="utf-8"))

    inference = raw.get("inference_payload", {})
    runtime_defaults = raw.get("runtime_defaults", {})
    execution_rules = raw.get("execution_rules", {})
    stop_take = execution_rules.get("stop_take", {})
    unsup = raw.get("unsupervised_gate", {})

    _append_issue(issues, not _as_bool(inference.get("executable", False)), "inference_payload.executable != true")
    _append_issue(issues, not inference.get("model_type"), "inference_payload.model_type missing")
    _append_issue(issues, not inference.get("payload_b64"), "inference_payload.payload_b64 missing")

    features = inference.get("features", []) or []
    _append_issue(issues, len(features) == 0, "inference_payload.features empty")
    _append_warn(warnings, len(features) < 21, f"inference_payload.features length suspicious: {len(features)}")

    target_classes = inference.get("target_classes", []) or []
    _append_issue(issues, len(target_classes) != 3, f"inference_payload.target_classes invalid: {target_classes}")
    if len(target_classes) == 3:
        tc = {int(x) for x in target_classes}
        _append_warn(warnings, tc != {-1, 0, 1}, f"target_classes differs from expected {{-1,0,1}}: {target_classes}")

    _append_issue(issues, not runtime_defaults.get("symbol"), "runtime_defaults.symbol missing")
    _append_issue(issues, not runtime_defaults.get("timeframe"), "runtime_defaults.timeframe missing")

    has_dynamic = bool(stop_take.get("dynamic_by_volatility", False))
    has_points = ("stop_loss_points" in stop_take) or ("take_profit_points" in stop_take)
    _append_warn(
        warnings,
        not (has_dynamic or has_points),
        "execution_rules.stop_take missing dynamic/points fields (runtime may fallback to config defaults)",
    )

    unsup_enabled = bool(unsup.get("enabled", False))
    strict_full_missing = unsup_enabled and not (unsup.get("scaler") and unsup.get("kmeans") and unsup.get("allowed_clusters"))
    if strict_unsup_full and strict_full_missing:
        issues.append("unsup_enabled_but_not_full_payload")

    diag = {
        "symbol": runtime_defaults.get("symbol"),
        "timeframe": runtime_defaults.get("timeframe"),
        "features": len(features),
        "target_classes": target_classes,
        "min_signal_confidence": raw.get("supervised", {}).get("params", {}).get("min_signal_confidence"),
        "unsup_enabled": unsup_enabled,
        "unsup_mode": "unknown",
    }

    # Dynamic validation using StrategyAdapter when dependencies are available.
    try:
        StrategyAdapter = importlib.import_module("xau_trader.strategy_adapter").StrategyAdapter
        adapter = StrategyAdapter(str(path))
        issues.extend(adapter.validate_artifact_contract())
        diag["features"] = len(adapter.feature_order)
        diag["target_classes"] = adapter.target_classes
        diag["min_signal_confidence"] = adapter.min_signal_confidence
        diag["unsup_enabled"] = adapter.unsup_enabled
        diag["unsup_mode"] = adapter.unsup_mode
        if adapter.unsup_enabled and adapter.unsup_mode == "score_fallback":
            if strict_unsup_full:
                issues.append("unsup_enabled_but_not_full_payload")
            else:
                warnings.append("unsup_enabled_with_score_fallback (full cluster gate payload not present)")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"dynamic_validation_skipped: {exc}")

    return issues, warnings, diag


def cli() -> None:
    parser = argparse.ArgumentParser(description="Validate trader strategy artifact contract (OK/FALHA)")
    parser.add_argument("--artifact", required=True, help="Path to artifact JSON")
    parser.add_argument(
        "--strict-unsup-full",
        action="store_true",
        help="Fail when unsupervised_gate.enabled=true but full unsup payload is missing",
    )
    args = parser.parse_args()

    artifact_path = Path(args.artifact)
    issues, warnings, diag = validate_artifact(artifact_path, strict_unsup_full=bool(args.strict_unsup_full))

    print(f"[artifact-validator] artifact={artifact_path}")
    if diag:
        print(
            "[artifact-validator] "
            f"symbol={diag.get('symbol')} timeframe={diag.get('timeframe')} "
            f"features={diag.get('features')} target_classes={diag.get('target_classes')} "
            f"min_conf={diag.get('min_signal_confidence')} unsup={diag.get('unsup_enabled')} mode={diag.get('unsup_mode')}"
        )

    for w in warnings:
        print(f"[artifact-validator] WARN: {w}")

    if issues:
        for i in issues:
            print(f"[artifact-validator] FAIL: {i}")
        print("[artifact-validator] STATUS=FALHA")
        raise SystemExit(2)

    print("[artifact-validator] STATUS=OK")


if __name__ == "__main__":
    cli()
