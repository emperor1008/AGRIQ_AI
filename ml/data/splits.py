"""Split building and leakage prevention (Phase 4).

Splits are built **before augmentation** and grouped by the strongest
available grouping key (field/location > plant > capture session > source >
image family). The split manifest records seed, distributions and duplicate
checks. Nothing here fabricates images or metrics — it only partitions real,
validated files.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

SPLIT_DIR = Path(__file__).resolve().parent / "splits"


class SplitError(Exception):
    """Raised when a split would leak or is built on invalid input."""


def build_splits(
    records: list[dict[str, Any]],
    *,
    seed: int,
    group_key: str = "group",
    ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
) -> dict[str, Any]:
    """Group-wise train/val/test split.

    ``records`` items need: ``path``, ``agriq_label``, ``group``. Records
    sharing a group always land in the same split — an original image and all
    its near-duplicates/augmented copies must share a group.
    """
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise SplitError("Split ratios must sum to 1.0")
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        for key in ("path", "agriq_label", group_key):
            if key not in rec:
                raise SplitError(f"Record missing '{key}': {rec}")
        groups.setdefault(rec[group_key], []).append(rec)

    # Sort groups deterministically then shuffle by seed.
    rng = random.Random(seed)
    group_ids = sorted(groups)
    rng.shuffle(group_ids)

    target = {
        "train": ratios[0] * len(records),
        "val": ratios[1] * len(records),
        "test": ratios[2] * len(records),
    }
    counts = {"train": 0, "val": 0, "test": 0}
    assignment: dict[str, str] = {}
    # Greedy largest-first assignment keeps ratios close for skewed groups.
    for gid in sorted(group_ids, key=lambda g: -len(groups[g])):
        remaining = [s for s in ("train", "val", "test") if counts[s] < target[s] - 1e-6]
        chosen = remaining[0] if remaining else "train"
        assignment[gid] = chosen
        counts[chosen] += len(groups[gid])

    splits: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    for gid, split in assignment.items():
        for rec in groups[gid]:
            splits[split].append(rec["path"])

    class_dist = _distribution(records, assignment, groups, "agriq_label")
    source_dist = _distribution(records, assignment, groups, group_key)
    return {
        "seed": seed,
        "group_key": group_key,
        "ratios": list(ratios),
        "counts": counts,
        "class_distribution": class_dist,
        "group_distribution": source_dist,
        "splits": {k: sorted(v) for k, v in splits.items()},
    }


def check_leakage(manifest: dict[str, Any], families: dict[str, str]) -> list[str]:
    """Verify no image family crosses splits.

    ``families`` maps image path → family id (e.g. original-image hash). Any
    family appearing in more than one split is a leak.
    """
    seen: dict[str, set[str]] = {}
    for split, paths in manifest["splits"].items():
        for path in paths:
            family = families.get(path, path)
            seen.setdefault(family, set()).add(split)
    return sorted(f"{fam}: {sorted(splits_)}" for fam, splits_ in seen.items() if len(splits_) > 1)


def family_id(path: str | Path) -> str:
    """Stable family identifier derived from a normalised stem.

    SHA-1 here is a non-cryptographic content key (bandit B324 suppressed):
    it only groups near-duplicate images, never protects a secret.
    """
    stem = Path(path).stem.lower()
    # Strip common augmentation suffixes so augmented copies share the family.
    for suffix in ("_rot90", "_rot180", "_rot270", "_flip", "_bright", "_aug"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return hashlib.sha1(stem.encode("utf-8"), usedforsecurity=False).hexdigest()  # nosec B324


def save_manifest(manifest: dict[str, Any], dataset_id: str) -> Path:
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    path = SPLIT_DIR / f"{dataset_id}_splits.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return path


def _distribution(
    records: list[dict[str, Any]],
    assignment: dict[str, str],
    groups: dict[str, list[dict[str, Any]]],
    field: str,
) -> dict[str, dict[str, int]]:
    dist: dict[str, dict[str, int]] = {"train": {}, "val": {}, "test": {}}
    for gid, split in assignment.items():
        for rec in groups[gid]:
            value = str(rec.get(field, "unknown"))
            dist[split][value] = dist[split].get(value, 0) + 1
    return dist
