"""Model export (Phase 4).

``python -m ml.training.export --config ml/configs/rice_classifier.yaml``

Exports the trained model to TorchScript (CPU-compatible), computes the
artifact checksum and appends a **draft** registry entry. Nothing becomes
production-serveable until a human approver sets ``approved_for_production:
true`` with their name in ``ml/models/registry.yaml``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

ML_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ML_DIR / "models" / "registry.yaml"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export(config_path: Path) -> Path:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("Export requires torch (training dependencies)") from exc

    checkpoint = ML_DIR / "models" / "artifacts" / f"{config['model_id']}_best.pt"
    if not checkpoint.exists():
        raise SystemExit("No trained checkpoint — run ml.training.train first")

    from torchvision import models

    model = getattr(models, config["architecture"])(weights=None)
    import torch.nn as nn

    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(config["classes"]))
    # Manual-run-only path: the checkpoint was produced by ml.training.train on
    # this machine (trusted, provenance-recorded). Weights-only load. B614 suppressed.
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)  # nosec B614
    model.load_state_dict(state)
    model.eval()

    example = torch.randn(1, 3, config["input_size"], config["input_size"])
    scripted = torch.jit.trace(model, example)
    out = ML_DIR / "models" / "artifacts" / f"{config['model_id']}_{checkpoint.stem}.torchscript.pt"
    scripted.save(str(out))

    artifact = {
        "model_id": config["model_id"],
        "artifact_path": str(out),
        "sha256": sha256_file(out),
        "size_bytes": out.stat().st_size,
        "input_size": config["input_size"],
        "classes": config["classes"],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "approved_for_production": False,  # human approval required — never self-approved
    }
    sidecar = out.with_suffix(".meta.json")
    sidecar.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Exported: {out}\nChecksum: {artifact['sha256']}\nDraft metadata: {sidecar}")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export trained model to TorchScript")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    export(args.config)


if __name__ == "__main__":
    main()
