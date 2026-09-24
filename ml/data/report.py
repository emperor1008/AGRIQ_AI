"""``python -m ml.data.report --dataset DATASET_ID`` (Phase 4).

Writes a human-readable dataset report next to the machine-readable
validation manifest. Reports only what the pipeline actually measured.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"


def report(dataset_id: str) -> Path:
    manifest_path = MANIFEST_DIR / f"{dataset_id}_validation.json"
    if not manifest_path.exists():
        raise SystemExit("No validation manifest — run ml.data.validate first")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    lines = [
        f"# Dataset report: {dataset_id}",
        "",
        f"Validated at: {data['validated_at']}",
        f"Original files: {data['original_files']}",
        f"Accepted: {data['accepted']}",
        f"Rejected: {data['rejected']}",
        "",
        "## Class distribution (accepted, provisional labels)",
        "",
    ]
    for label, count in sorted(data["class_counts"].items()):
        lines.append(f"- {label}: {count}")
    lines += ["", "## Rejections", ""]
    for rej in data["rejections"][:200]:
        detail = rej.get("path") or json.dumps(rej.get("conflict", {}))
        lines.append(f"- {rej['reason']}: {detail}")
    if len(data["rejections"]) > 200:
        lines.append(f"- ... {len(data['rejections']) - 200} more (see machine manifest)")

    out = MANIFEST_DIR / f"{dataset_id}_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {out}")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write a human-readable dataset report")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args(argv)
    report(args.dataset)


if __name__ == "__main__":
    main(sys.argv[1:])
