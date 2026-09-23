"""Training-run provenance recorder (Phase 4).

Every manual training run must record: git commit, config checksum, dataset
version, split-manifest checksum, architecture, weights licence, seed, dates,
framework version, hardware, hyperparameters and augmentation config. Metrics
are recorded **only** when training actually completed — never invented.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent / "runs"


class ProvenanceError(Exception):
    """Raised when provenance requirements are unmet."""


def git_commit(repo_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ProvenanceError("Training requires a git commit for provenance") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_run_record(config_path: Path, split_manifest_path: Path, dataset_id: str) -> dict:
    """Create a provenance skeleton with real environment facts."""
    repo_dir = Path(__file__).resolve().parents[2]
    return {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{dataset_id}",
        "git_commit": git_commit(repo_dir),
        "config_checksum": sha256_file(config_path),
        "dataset_id": dataset_id,
        "split_manifest_checksum": sha256_file(split_manifest_path),
        "framework_version": _framework_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "started",   # completed | failed — set by the trainer
        "validation_metrics": None,  # recorded only after real training
        "test_metrics": None,        # recorded ONLY at final evaluation
        "notes": "",
    }


def finalise(record: dict, *, status: str, checkpoint: str | None = None) -> Path:
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    record["status"] = status
    if checkpoint:
        record["best_checkpoint"] = checkpoint
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{record['run_id']}.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out


def _framework_version() -> str:
    try:
        import torch

        return f"torch {torch.__version__}"
    except ImportError:
        return "torch not installed (training dependencies not present)"
