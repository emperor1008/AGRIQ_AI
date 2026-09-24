"""Manual training entry point (Phase 4).

``python -m ml.training.train --config ml/configs/rice_classifier.yaml``

Hard gates before any training begins:
1. The config's dataset must have ``status: approved`` in the registry.
2. A leakage-free split manifest must exist.
3. Training dependencies (torch/torchvision) must be installed — they are
   deliberately NOT part of the web application's requirements.

The web application never imports this module; nothing here runs at app start.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .provenance import ProvenanceError, finalise, new_run_record

ML_DIR = Path(__file__).resolve().parents[1]
SPLIT_DIR = ML_DIR / "data" / "splits"


def training_dependencies_available() -> bool:
    try:
        import torch  # noqa: F401
        import torchvision  # noqa: F401

        return True
    except ImportError:
        return False


def preflight(config: dict, config_path: Path) -> dict:
    """Validate every gate; returns the split manifest."""
    from ml.data.registry import get_dataset

    entry = get_dataset(config["dataset_id"])
    if entry is None:
        raise SystemExit(f"Unknown dataset '{config['dataset_id']}'")
    if entry["status"] != "approved":
        raise SystemExit(
            f"Dataset '{config['dataset_id']}' is '{entry['status']}' — training requires 'approved'. "
            "Complete licence verification and quality review first."
        )
    split_path = SPLIT_DIR / f"{config['dataset_id']}_splits.json"
    if not split_path.exists():
        raise SystemExit("No split manifest — run ml.data.build_splits first")
    manifest = json.loads(split_path.read_text(encoding="utf-8"))
    if manifest.get("leakage_violations"):
        raise SystemExit("Split manifest reports leakage — resolve before training")
    if not training_dependencies_available():
        raise SystemExit(
            "Training dependencies (torch/torchvision) are not installed. "
            "They are intentionally separate from the web app's requirements."
        )
    try:
        record = new_run_record(config_path, split_path, config["dataset_id"])
    except ProvenanceError as exc:
        raise SystemExit(str(exc))
    return manifest, record  # type: ignore[return-value]


def train(config_path: Path) -> None:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest, record = preflight(config, config_path)

    # NOTE: the actual training loop is intentionally documented but requires
    # the heavyweight deps; the structure below runs once they exist.
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader
    from torchvision import models

    from ml.inference.preprocess import build_training_transforms, training_dataset

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(config["training"]["seed"])

    model = getattr(models, config["architecture"])(weights="DEFAULT")
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(config["classes"]))
    model = model.to(device)

    datasets = training_dataset(manifest, config)
    loaders = {
        split: DataLoader(ds, batch_size=config["training"]["batch_size"], shuffle=(split == "train"))
        for split, ds in datasets.items()
    }

    optimiser = torch.optim.AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )
    criterion = nn.CrossEntropyLoss()

    best_acc, patience, best_state = 0.0, 0, None
    for epoch in range(config["training"]["epochs"]):
        model.train()
        for images, labels in loaders["train"]:
            images, labels = images.to(device), labels.to(device)
            optimiser.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimiser.step()

        # Validation accuracy
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for images, labels in loaders["val"]:
                images, labels = images.to(device), labels.to(device)
                correct += (model(images).argmax(1) == labels).sum().item()
                total += labels.size(0)
        val_acc = correct / max(total, 1)
        print(f"epoch {epoch}: val_acc={val_acc:.4f}")
        if val_acc > best_acc:
            best_acc, patience = val_acc, 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience += 1
            if patience >= config["training"]["early_stopping_patience"]:
                record["notes"] = f"early stop at epoch {epoch}"
                break

    record["validation_metrics"] = {"best_val_accuracy": round(best_acc, 4)}
    out_dir = ML_DIR / "models" / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = out_dir / f"{config['model_id']}_best.pt"
    torch.save(best_state or model.state_dict(), checkpoint)
    finalise(record, status="completed", checkpoint=str(checkpoint))
    print(f"Training complete: {checkpoint}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manual model training (never runs from the web app)")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        train(args.config)
    except SystemExit:
        raise
    except Exception as exc:  # record real failures honestly
        record = {"run_id": "unknown", "status": "failed", "notes": repr(exc)}
        from .provenance import finalise

        finalise(record, status="failed")
        print(f"Training failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main(sys.argv[1:])
