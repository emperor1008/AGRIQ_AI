"""``python -m ml.data.validate --dataset DATASET_ID`` (Phase 4).

Extracts the downloaded archive, validates every image (decode, format,
dimensions, colour channels), detects exact/perceptual duplicates and
conflicting labels, quarantines invalid files and writes machine-readable
rejection reports. Originals remain immutable; valid files are copied to
``validated/`` with a per-file checksum manifest.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .duplicates import conflicting_label_report, exact_duplicate_map, perceptual_duplicate_groups
from .image_checks import decode_verified, image_statistics, sha256_file
from .registry import get_dataset
from .splits import family_id

BASE = Path(__file__).resolve().parent
RAW_DIR = BASE / "raw"
VALIDATED_DIR = BASE / "validated"
QUARANTINE_DIR = BASE / "quarantined"
MANIFEST_DIR = BASE / "manifests"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def validate(dataset_id: str, label_overrides: dict[str, str] | None = None) -> Path:
    """Validate a downloaded dataset; returns the validation manifest path."""
    entry = get_dataset(dataset_id)
    if entry is None:
        raise SystemExit(f"Dataset '{dataset_id}' is not in the registry")
    archive = RAW_DIR / f"{dataset_id}.archive"
    if not archive.exists():
        raise SystemExit("No downloaded archive found — run ml.data.download first")

    extract_dir = RAW_DIR / f"{dataset_id}_extracted"
    if not extract_dir.exists():
        extract_dir.mkdir(parents=True)
        shutil.unpack_archive(archive, extract_dir)

    files = sorted(p for p in extract_dir.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    accepted: list[dict] = []
    rejections: list[dict] = []
    checksums: dict[str, str] = {}

    for path in files:
        rel = str(path.relative_to(extract_dir))
        try:
            img = decode_verified(path)
            stats = image_statistics(img)
        except (ValueError, OSError) as exc:
            rejections.append({"path": rel, "reason": f"decode_or_dimension: {exc}"})
            continue
        digest = sha256_file(path)
        checksums[rel] = digest
        label = (label_overrides or {}).get(rel) or _infer_label(rel, entry)
        accepted.append(
            {
                "path": rel,
                "sha256": digest,
                "label": label,
                "family": family_id(rel),
                **stats,
            }
        )

    # Exact duplicates: keep first path per hash, reject the rest.
    dup_map = exact_duplicate_map([extract_dir / r["path"] for r in accepted])
    for digest, members in dup_map.items():
        for member in members[1:]:
            rel = str(Path(member).relative_to(extract_dir))
            rejections.append({"path": rel, "reason": "exact_duplicate"})
            accepted = [a for a in accepted if a["path"] != rel]

    # Perceptual duplicates (same label ⇒ keep first; different label ⇒ conflict report).
    conflicts = conflicting_label_report(accepted)
    conflict_paths = {p for c in conflicts for p in c["paths"]}
    pgroups = perceptual_duplicate_groups([extract_dir / a["path"] for a in accepted])
    for group in pgroups:
        rels = [str(Path(p).relative_to(extract_dir)) for p in group]
        for rel in rels[1:]:
            if rel not in conflict_paths:
                rejections.append({"path": rel, "reason": "perceptual_duplicate"})
                accepted = [a for a in accepted if a["path"] != rel]
    for conflict in conflicts:
        rejections.append({"conflict": conflict, "reason": "conflicting_duplicate_labels"})

    # Quarantine copies of rejected files (originals untouched).
    if rejections:
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        qdir = QUARANTINE_DIR / dataset_id
        qdir.mkdir(exist_ok=True)
        for rej in rejections:
            rej_path = rej.get("path")
            if rej_path:
                src = extract_dir / rej_path
                if src.exists():
                    shutil.copy2(src, qdir / src.name)

    # Copy accepted files to validated/ (immutably named by family+hash).
    validated: list[dict] = []
    VALIDATED_DIR.mkdir(parents=True, exist_ok=True)
    vdir = VALIDATED_DIR / dataset_id
    vdir.mkdir(exist_ok=True)
    for rec in accepted:
        src = extract_dir / rec["path"]
        target = vdir / f"{rec['family']}_{rec['sha256'][:12]}{src.suffix.lower()}"
        if not target.exists():
            shutil.copy2(src, target)
        validated.append({**rec, "stored_path": str(target)})

    manifest = {
        "dataset_id": dataset_id,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "original_files": len(files),
        "accepted": len(validated),
        "rejected": len(rejections),
        "class_counts": _counts(validated),
        "records": validated,
        "rejections": rejections,
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    out = MANIFEST_DIR / f"{dataset_id}_validation.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"accepted={len(validated)} rejected={len(rejections)} manifest={out}")
    return out


def _counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["label"]] = counts.get(rec["label"], 0) + 1
    return counts


def _infer_label(rel_path: str, entry: dict) -> str:
    """Derive a provisional label from directory/file naming for review only.

    This is **provisional**: real labels must pass the reviewed label mapping
    (ml/data/label_mapping.py) before any training. Unknown names map to
    ``unsupported`` — never guessed.
    """
    from .label_mapping import agriq_labels

    haystack = rel_path.lower().replace("\\", "_").replace("-", "_")
    crop = entry["crop"][0] if entry["crop"] else "rice"
    allowed = agriq_labels(crop)
    for token in sorted(allowed, key=len, reverse=True):
        if token in haystack:
            return token
    return "unsupported"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate a downloaded dataset")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args(argv)
    validate(args.dataset)


if __name__ == "__main__":
    main(sys.argv[1:])
