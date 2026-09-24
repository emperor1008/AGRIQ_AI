"""Final evaluation (Phase 4).

``python -m ml.training.evaluate --config ml/configs/rice_classifier.yaml --predictions eval.json``

The test split is consumed **only** here, only after model selection and
calibration are complete. Input is a JSON file of real prediction records:
``[{image, y_true, y_pred, confidence, correct}]`` produced by an actual
inference sweep. No metric is ever invented.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ..evaluation.metrics import full_report

REPORT_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "reports"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Final evaluation on the untouched test split")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--cohort", default="controlled", choices=["controlled", "field"])
    args = parser.parse_args(argv)

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    data = json.loads(args.predictions.read_text(encoding="utf-8"))
    if not data:
        print("No prediction records — refusing to fabricate metrics", file=sys.stderr)
        raise SystemExit(1)

    labels = config["classes"]
    report = full_report(
        [d["y_true"] for d in data],
        [d["y_pred"] for d in data],
        labels,
        [d.get("confidence", 0.0) for d in data],
        [d.get("correct", False) for d in data],
    )
    report.update(
        {
            "model_id": config["model_id"],
            "cohort": args.cohort,
            "n_samples": len(data),
            "note": "Controlled-image and field-image cohorts are NEVER merged into one number.",
        }
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{config['model_id']}_{args.cohort}_evaluation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("macro_f1", "balanced_accuracy", "n_samples")}, indent=2))
    print(f"Full report: {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
