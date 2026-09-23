"""``python -m ml.data.build_splits --dataset DATASET_ID`` (Phase 4).

Builds grouped train/val/test splits from a validation manifest with
leakage checks. Splitting happens strictly **before** any augmentation.
"""
from __future__ import annotations

import argparse
import json
import sys

from .splits import SPLIT_DIR, build_splits, check_leakage, family_id, save_manifest
from .registry import get_dataset

MANIFEST_DIR = __import__("pathlib").Path(__file__).resolve().parent / "manifests"


def build(dataset_id: str, seed: int = 20260923) -> dict:
    validation_manifest = MANIFEST_DIR / f"{dataset_id}_validation.json"
    if not validation_manifest.exists():
        raise SystemExit("No validation manifest — run ml.data.validate first")
    data = json.loads(validation_manifest.read_text(encoding="utf-8"))
    records = [
        {"path": rec["stored_path"], "agriq_label": rec["label"], "group": rec["family"]}
        for rec in data["records"]
    ]
    if not records:
        raise SystemExit("Validation manifest contains no accepted records")

    manifest = build_splits(records, seed=seed, group_key="group")
    families = {rec["stored_path"]: rec["family"] for rec in data["records"]}
    leaks = check_leakage(manifest, families)
    manifest["dataset_id"] = dataset_id
    manifest["leakage_violations"] = leaks
    entry = get_dataset(dataset_id) or {}
    manifest["dataset_status"] = entry.get("status", "unknown")

    path = save_manifest(manifest, dataset_id)
    print(f"counts={manifest['counts']} leaks={len(leaks)} manifest={path}")
    if leaks:
        print("LEAKAGE DETECTED — resolve before training", file=sys.stderr)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build leakage-checked dataset splits")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args(argv)
    build(args.dataset, seed=args.seed)


if __name__ == "__main__":
    main(sys.argv[1:])
