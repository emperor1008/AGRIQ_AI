"""Duplicate detection (Phase 4).

- Exact duplicates: identical SHA-256.
- Perceptual duplicates: images downsampled to a small grayscale grid whose
  entries differ by less than a documented threshold. A simple, transparent
  heuristic — not a learned embedding.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .image_checks import decode_verified, sha256_file

PERCEPTUAL_GRID = 16
PERCEPTUAL_THRESHOLD = 4.0  # mean absolute pixel difference on 0-255 grid


def exact_duplicate_map(paths: list[Path]) -> dict[str, list[str]]:
    """Map sha256 → list of paths sharing that hash (len>1 means duplicates)."""
    seen: dict[str, list[str]] = {}
    for path in paths:
        digest = sha256_file(path)
        seen.setdefault(digest, []).append(str(path))
    return {digest: members for digest, members in seen.items() if len(members) > 1}


def _grid_signature(path: Path) -> list[float] | None:
    try:
        img = decode_verified(path)
    except (ValueError, OSError):
        return None
    img = img.convert("L").resize((PERCEPTUAL_GRID, PERCEPTUAL_GRID))
    return list(img.getdata())


def perceptual_duplicate_groups(
    paths: list[Path], threshold: float = PERCEPTUAL_THRESHOLD
) -> list[list[str]]:
    """Group paths whose grid signatures are near-identical."""
    signatures: list[tuple[str, list[float]]] = []
    for path in paths:
        sig = _grid_signature(path)
        if sig is not None:
            signatures.append((str(path), sig))
    assigned: list[list[str]] = []
    used: set[int] = set()
    for i, (path_i, sig_i) in enumerate(signatures):
        if i in used:
            continue
        group = [path_i]
        used.add(i)
        for j in range(i + 1, len(signatures)):
            if j in used:
                continue
            sig_j = signatures[j][1]
            diff = sum(abs(a - b) for a, b in zip(sig_i, sig_j)) / len(sig_i)
            if diff < threshold:
                group.append(signatures[j][0])
                used.add(j)
        if len(group) > 1:
            assigned.append(group)
    return assigned


def conflicting_label_report(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find near-duplicate files assigned different labels.

    ``records`` items need ``path`` and ``agriq_label``.
    """
    conflicts: list[dict[str, Any]] = []
    label_by_path = {str(r["path"]): r["agriq_label"] for r in records}
    paths = sorted(label_by_path)
    groups = perceptual_duplicate_groups([Path(p) for p in paths])
    for group in groups:
        labels = {label_by_path.get(p, "unknown") for p in group}
        if len(labels) > 1:
            conflicts.append({"paths": group, "labels": sorted(labels)})
    return conflicts
