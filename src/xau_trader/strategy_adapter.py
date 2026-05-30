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

        self.threshold = float(self.supervised_params.get("move_threshold_bps", 3.0)) / 10_000.0
        self.min_signal_confidence = float(self.supervised_params.get("min_signal_confidence", 0.0))

        # Unsupervised gate runtime contract.
        self.unsup_enabled = bool(self.unsup.get("enabled", False))
        self.unsup_allow_score_threshold_bps = float(self.unsup.get("allow_score_threshold_bps", 0.0))
        self.unsup_feature_order: list[str] = list(self.unsup.get("feature_order", self.feature_order))
        self.unsup_mode = "disabled"
        self.unsup_centroids: np.ndarray | None = None
        self.unsup_scaler_mean: np.ndarray | None = None
        self.unsup_scaler_scale: np.ndarray | None = None
        self.unsup_allowed_clusters: set[int] = set()
        self.unsup_cluster_scores_bps: dict[int, float] = {}
        if self.unsup_enabled:
            self._init_unsup_gate()

    def _init_unsup_gate(self) -> None:
        scaler = self.unsup.get("scaler", {}) or {}
        kmeans = self.unsup.get("kmeans", {}) or {}
        means = scaler.get("mean") or self.unsup.get("scaler_mean")
        scales = scaler.get("scale") or self.unsup.get("scaler_scale")
        centers = (
            kmeans.get("centroids")
            or kmeans.get("centers")
            or self.unsup.get("kmeans_centroids")
            or self.unsup.get("cluster_centers")
        )
        allowed = self.unsup.get("allowed_clusters") or self.unsup.get("allowed_cluster_ids") or []
        cluster_scores = self.unsup.get("cluster_scores_bps") or self.unsup.get("cluster_mean_ret_bps") or {}

        full_payload_ok = means is not None and scales is not None and centers is not None and len(allowed) > 0
        if full_payload_ok:
            mean_np = np.asarray(means, dtype=np.float32)
            scale_np = np.asarray(scales, dtype=np.float32)
            cent_np = np.asarray(centers, dtype=np.float32)
            if mean_np.ndim != 1 or scale_np.ndim != 1 or cent_np.ndim != 2:
                raise RuntimeError("Invalid unsupervised_gate payload shape (scaler/kmeans).")
            n_feat = len(self.unsup_feature_order)
            if len(mean_np) != n_feat or len(scale_np) != n_feat or int(cent_np.shape[1]) != n_feat:
                raise RuntimeError(
                    "unsupervised_gate feature dimension mismatch with feature_order. "
                    f"expected={n_feat} mean={len(mean_np)} scale={len(scale_np)} centers={int(cent_np.shape[1])}"
                )
            self.unsup_scaler_mean = mean_np
            self.unsup_scaler_scale = np.where(np.abs(scale_np) < 1.0e-12, 1.0, scale_np)
            self.unsup_centroids = cent_np
            self.unsup_allowed_clusters = {int(x) for x in allowed}
            if isinstance(cluster_scores, dict):
                self.unsup_cluster_scores_bps = {int(k): float(v) for k, v in cluster_scores.items()}
            self.unsup_mode = "full"
            return

        # Fallback for older artifacts: keep only score gate to avoid silent no-gate.
        self.unsup_mode = "score_fallback"

    def validate_artifact_contract(self) -> list[str]:
        issues: list[str] = []
        if not self.feature_order:
            issues.append("missing_inference_features")
        if len(self.target_classes) != 3:
            issues.append("invalid_target_classes")
        return issues

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

    def _resolve_stop_take_distances(
        self,
        features: dict[str, float],
        point: float,
        fallback_sl_points: float,
        fallback_rr: float,
    ) -> tuple[float, float]:
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

    def _unsup_pass(self, features: dict[str, float], score_bps: float) -> tuple[bool, dict[str, Any]]:
        if not self.unsup_enabled:
            return True, {"mode": "disabled"}

        if self.unsup_mode == "full":
            x = np.asarray([float(features.get(k, 0.0)) for k in self.unsup_feature_order], dtype=np.float32)
            xz = (x - self.unsup_scaler_mean) / self.unsup_scaler_scale  # type: ignore[operator]
            d2 = np.sum((self.unsup_centroids - xz[None, :]) ** 2, axis=1)  # type: ignore[operator]
            cluster_id = int(np.argmin(d2))
            allowed = cluster_id in self.unsup_allowed_clusters
            if not allowed:
                return False, {
                    "mode": "full",
                    "cluster_id": cluster_id,
                    "allowed_clusters": sorted(self.unsup_allowed_clusters),
                    "cluster_score_bps": float(self.unsup_cluster_scores_bps.get(cluster_id, 0.0)),
                }
            return True, {
                "mode": "full",
                "cluster_id": cluster_id,
                "allowed_clusters": sorted(self.unsup_allowed_clusters),
                "cluster_score_bps": float(self.unsup_cluster_scores_bps.get(cluster_id, 0.0)),
            }

        # score_fallback mode for backward compatibility artifacts.
        # Accept only if signed score (long-positive / short-negative) exceeds configured bps threshold.
        pass_score = float(score_bps) >= float(self.unsup_allow_score_threshold_bps)
        return pass_score, {
            "mode": "score_fallback",
            "score_bps": float(score_bps),
            "allow_score_threshold_bps": float(self.unsup_allow_score_threshold_bps),
        }

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

        unsup_meta: dict[str, Any] = {"mode": "disabled", "passed": True}
        if action != "hold":
            signed_score_bps = float(score * 10000.0) if direction >= 0 else float(-score * 10000.0)
            gate_ok, gate_info = self._unsup_pass(features, signed_score_bps)
            unsup_meta = {"passed": bool(gate_ok), **gate_info}
            if not gate_ok:
                action = "hold"

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
                "unsup_gate": unsup_meta,
            },
        )
