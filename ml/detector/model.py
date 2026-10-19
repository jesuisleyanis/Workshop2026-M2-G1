"""Chargement du modèle IsolationForest + baseline_stats.json produits par ml/training."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from ml.shared.features import FEATURE_NAMES, validate_vector


class ModelLoadError(RuntimeError):
    """Artefacts absents, altérés ou incompatibles avec la définition des features."""


@dataclass
class LoadedModel:
    model: object  # sklearn.ensemble.IsolationForest
    stats: dict

    @property
    def version(self) -> str:
        return self.stats["model_version"]

    @property
    def threshold(self) -> float:
        return float(self.stats["threshold"])

    @property
    def guardrail_z(self) -> float:
        return float(self.stats["guardrail_z"])

    def score(self, vector: list[float]) -> float:
        """Score d'anomalie dans (0, 1], plus haut = plus anormal (= -score_samples)."""
        validate_vector(vector)
        return float(-self.model.score_samples(np.asarray([vector], dtype=float))[0])


def load_model(model_dir: str | Path) -> LoadedModel:
    d = Path(model_dir)
    model_path, stats_path = d / "model.joblib", d / "baseline_stats.json"
    if not model_path.is_file() or not stats_path.is_file():
        raise ModelLoadError(f"model.joblib / baseline_stats.json introuvables dans {d}")
    stats = json.loads(stats_path.read_text())

    if stats.get("feature_names") != list(FEATURE_NAMES):
        raise ModelLoadError(
            "feature_names du modèle différents de ml.shared.features.FEATURE_NAMES : ré-entraîner"
        )
    # joblib = pickle : on ne désérialise un artefact que s'il correspond au hash publié
    # par le training (détecte altération/remplacement du fichier).
    expected = stats.get("model_sha256")
    actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if expected != actual:
        raise ModelLoadError("model.joblib ne correspond pas au sha256 de baseline_stats.json")

    payload = joblib.load(model_path)
    return LoadedModel(model=payload["model"], stats=stats)
