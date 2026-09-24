"""Calibration (Phase 4): temperature scaling on the validation split.

Raw softmax output is **never** shown to farmers. Calibration converts logits
to honest probabilities using a temperature fitted on the validation split;
ECE and a reliability diagram are recorded. Runs manually only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

import yaml

from ..evaluation.metrics import expected_calibration_error

CALIB_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "reports"


def fit_temperature(logits: Sequence[Sequence[float]], labels: Sequence[int], max_iter: int = 200) -> float:
    """Fit a single temperature parameter by gradient descent on NLL."""
    if not logits or len(logits) != len(labels):
        raise ValueError("Calibration requires real logits and labels of equal length")
    import torch

    tensor_logits = torch.tensor(logits, dtype=torch.float32)
    tensor_labels = torch.tensor(labels, dtype=torch.long)
    log_temperature = torch.zeros(1, requires_grad=True)
    optimiser = torch.optim.LBFGS([log_temperature], max_iter=max_iter)

    def closure():
        optimiser.zero_grad()
        loss = torch.nn.functional.cross_entropy(tensor_logits / log_temperature.exp(), tensor_labels)
        loss.backward()
        return loss

    optimiser.step(closure)
    return float(log_temperature.exp().item())


def apply_temperature(logits: Sequence[float], temperature: float) -> list[float]:
    """Temperature-scaled softmax probabilities."""
    if temperature <= 0:
        raise ValueError("Temperature must be positive")
    scaled = [v / temperature for v in logits]
    exps = [math.exp(v) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Calibrate a trained model on the validation split")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--logits", required=True, type=Path, help="JSON: [{logits, label}] from val split")
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))

    data = json.loads(args.logits.read_text(encoding="utf-8"))
    temperature = fit_temperature([d["logits"] for d in data], [d["label"] for d in data])
    confidences, correct = [], []
    for d in data:
        probs = apply_temperature(d["logits"], temperature)
        pred = max(range(len(probs)), key=lambda i: probs[i])
        confidences.append(max(probs))
        correct.append(pred == d["label"])

    ece = expected_calibration_error(confidences, correct)
    CALIB_DIR.mkdir(parents=True, exist_ok=True)
    out = CALIB_DIR / f"{config['model_id']}_calibration.json"
    out.write_text(
        json.dumps(
            {
                "model_id": config["model_id"],
                "method": "temperature_scaling",
                "temperature": round(temperature, 6),
                "ece_before_samples": "see evaluation run",
                "ece_after": ece,
                "n_samples": len(data),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"temperature={temperature:.4f} ECE={ece} → {out}")


if __name__ == "__main__":
    main()
