from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import numpy as np
import xgboost as xgb

from .types import Signal


class StrategyAdapter:
    def __init__(self, artifact_path: str) -> None:
        raw = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
        self.artifact = raw
        self.supervised = raw.get("supervised", {})
        self.supervised_params = self.supervised.get("params", {})
        self.strategy_kwargs = self.supervised_params.get("strategy_kwargs", {})
        self.runtime_defaults = raw.get("runtime_defaults", {})
        self.decision_rules = raw.get("decision_rules", {})
        self.execution_rules = raw.get("execution_rules", {})
        self.stop_take_rules = self.execution_rules.get("stop_take", {})
        self.cost_rules = self.execution_rules.get("costs", {})
        self.position_lock_rules = self.execution_rules.get("position_lock", {})
        self.symbol_constraints = self.execution_rules.get("symbol_constraints", {})
        self.unsup = raw.get("unsupervised_gate", {"enabled": False})

        # Hard safety gate: refuse execution without serialized inference payload.
        # This executor must mirror training behavior; heuristics are not acceptable for production.
        self.inference_payload = raw.get("inference_payload", {})
        self.model_payload = self.inference_payload.get("payload_b64")
        self.model_format = self.inference_payload.get("model_type")
        self.model_executable = bool(self.inference_payload.get("executable", False))
        if (not self.model_executable) or (self.model_payload is None) or (self.model_format is None):
            raise RuntimeError(
                "Artifact missing executable model payload "
                "(expected inference_payload.executable=true, inference_payload.model_type, "
                "and inference_payload.payload_b64). "
                "Rebuild combined artifact from training pipeline with serialized model included."
            )
        raw_bytes = base64.b64decode(str(self.model_payload))
        self.booster = xgb.Booster()
        self.booster.load_model(bytearray(raw_bytes))
        self.feature_order: list[str] = list(self.inference_payload.get("features", []))
        if not self.feature_order:
            raise RuntimeError("Artifact inference_payload.features is empty.")
        self.target_classes: list[int] = [int(x) for x in self.inference_payload.get("target_classes", [-1, 0, 1])]
        if len(self.target_classes) != 3:
            raise RuntimeError(f"Unexpected target_classes: {self.target_classes}")

        self.threshold = float(
            self.supervised_params.get("move_threshold_bps", 3.0)
        ) / 10_000.0
        self.min_signal_confidence = float(self.supervised_params.get("min_signal_confidence", 0.0))

    def runtime_from_artifact(self) -> dict[str, Any]:
        return {
            "symbol": self.runtime_defaults.get("symbol"),
            "timeframe": self.runtime_defaults.get("timeframe"),
            "risk_per_trade_pct": self.runtime_defaults.get("risk_per_trade_pct"),
            "max_open_positions": self.position_lock_rules.get("max_open_positions"),
            "slippage_points": self.cost_rules.get("slippage_points"),
            "commission_per_lot_per_side": self.cost_rules.get("commission_per_lot_per_side"),
            "swap_per_lot_per_day": self.cost_rules.get("swap_per_lot_per_day"),
        }

    def _resolve_stop_take_distances(self, features: dict[str, float], point: float, fallback_sl_points: float, fallback_rr: float) -> tuple[float, float]:
        current_price = float(features["last_price"])
        vol = float(features["range_14"])
        rules = self.stop_take_rules or {}

        stop_points = rules.get("stop_loss_points")
        tp_points = rules.get("take_profit_points")
        rr = float(rules.get("risk_reward_ratio", fallback_rr))

        if stop_points is not None:
            stop_distance = float(stop_points) * point
            if tp_points is not None:
                take_profit_distance = float(tp_points) * point
            else:
                take_profit_distance = stop_distance * rr
            return stop_distance, take_profit_distance

        if not rules:
            stop_distance = float(fallback_sl_points) * point
            take_profit_distance = stop_distance * float(fallback_rr)
            return stop_distance, take_profit_distance

        dynamic_by_vol = bool(rules.get("dynamic_by_volatility", True))
        vol_stop_k = float(rules.get("vol_stop_k", 2.0))
        vol_tp_k = float(rules.get("vol_tp_k", 2.4))
        min_stop_pct = float(rules.get("min_stop_loss_pct", 0.0025))
        max_stop_pct = float(rules.get("max_stop_loss_pct", 0.015))

        if dynamic_by_vol:
            stop_distance = vol * vol_stop_k
            tp_distance = vol * vol_tp_k
        else:
            stop_distance = vol
            tp_distance = stop_distance * rr

        min_stop_abs = current_price * min_stop_pct
        max_stop_abs = current_price * max_stop_pct
        stop_distance = max(min_stop_abs, min(max_stop_abs, stop_distance))
        take_profit_distance = max(stop_distance * rr, tp_distance)
        return stop_distance, take_profit_distance

    def predict(
        self,
        features: dict[str, float],
        point: float,
        fallback_sl_points: float,
        fallback_rr: float,
    ) -> Signal:
        x_vec = np.asarray([[float(features.get(k, 0.0)) for k in self.feature_order]], dtype=np.float32)
        probs = self.booster.predict(xgb.DMatrix(x_vec))
        p = probs[0]
        pred_idx = int(np.argmax(p))
        confidence = float(p[pred_idx])
        direction = int(self.target_classes[pred_idx])
        raw_action = "hold"
        if direction > 0:
            raw_action = "long"
        elif direction < 0:
            raw_action = "short"
        if confidence < self.min_signal_confidence:
            action = "hold"
        elif direction > 0:
            action = "long"
        elif direction < 0:
            action = "short"
        else:
            action = "hold"
        score = float(p[2] - p[0]) if len(p) == 3 else 0.0

        stop_distance, take_profit_distance = self._resolve_stop_take_distances(
            features=features,
            point=point,
            fallback_sl_points=fallback_sl_points,
            fallback_rr=fallback_rr,
        )
        return Signal(
            action=action,
            confidence=confidence,
            stop_distance=stop_distance,
            take_profit_distance=take_profit_distance,
            meta={
                "raw_score": score,
                "threshold": self.threshold,
                "min_signal_confidence": self.min_signal_confidence,
                "probs": [float(v) for v in p.tolist()],
                "class_prob_map": {
                    str(self.target_classes[0]): float(p[0]),
                    str(self.target_classes[1]): float(p[1]),
                    str(self.target_classes[2]): float(p[2]),
                },
                "pred_class": direction,
                "raw_action": raw_action,
            },
        )
