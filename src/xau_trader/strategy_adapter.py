from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import Signal


class StrategyAdapter:
    def __init__(self, artifact_path: str) -> None:
        raw = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
        self.artifact = raw
        self.supervised = raw.get("supervised", {})
        self.supervised_params = self.supervised.get("params", {})
        self.strategy_kwargs = self.supervised_params.get("strategy_kwargs", {})
        self.unsup = raw.get("unsupervised_gate", {"enabled": False})
        self.threshold = float(
            self.supervised_params.get("move_threshold_bps", 3.0)
        ) / 10_000.0
        # Optional SL/TP knobs from artifact; safe defaults preserve current behavior.
        self.sl_range_mult = float(self.strategy_kwargs.get("sl_range_mult", 1.2))
        self.tp_rr = float(self.strategy_kwargs.get("tp_rr", 1.5))
        self.min_stop_distance = float(self.strategy_kwargs.get("min_stop_distance", 0.6))

    def predict(self, features: dict[str, float]) -> Signal:
        score = float(features["momentum_5"] * 0.6 + features["momentum_20"] * 0.4)
        confidence = min(1.0, abs(score) / max(self.threshold, 1e-8))
        if score > self.threshold:
            action = "long"
        elif score < -self.threshold:
            action = "short"
        else:
            action = "hold"

        stop_distance = max(self.min_stop_distance, features["range_14"] * self.sl_range_mult)
        take_profit_distance = stop_distance * self.tp_rr
        return Signal(
            action=action,
            confidence=confidence,
            stop_distance=stop_distance,
            take_profit_distance=take_profit_distance,
            meta={"raw_score": score, "threshold": self.threshold},
        )
