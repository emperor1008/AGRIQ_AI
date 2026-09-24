"""``python -m ml.data.download --dataset DATASET_ID`` (Phase 4).

Downloads a dataset from its **original registered source** only, computes a
SHA-256 archive checksum and writes a manifest. Any dataset not registered is
refused; anything already downloaded is skipped (immutable raw storage).
No dataset in the current registry has been downloaded — this module exists so
the ingestion workflow is ready before any licence review completes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .image_checks import sha256_file
from .registry import get_dataset, load_registry

RAW_DIR = Path(__file__).resolve().parent / "raw"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"

# 5 GiB cap on archives — a sanity limit, configurable per-run.
MAX_ARCHIVE_BYTES = 5 * 1024 ** 3


def download(dataset_id: str, *, url_override: str | None = None, timeout: int = 120) -> Path:
    """Download the dataset archive from the registered original source."""
    entry = get_dataset(dataset_id)
    if entry is None:
        raise SystemExit(f"Dataset '{dataset_id}' is not in the registry")
    url = url_override or entry["original_source_url"]
    if not url.lower().startswith(("https://", "http://")):
        raise SystemExit("Refusing to download from a non-HTTP(S) source")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / f"{dataset_id}.archive"
    if target.exists():
        print(f"Raw archive already exists (immutable): {target}")
        return target

    import requests  # local import: keeps web-app dependency surface unchanged

    print(f"Downloading {dataset_id} from {url} ...")
    with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as resp:
        resp.raise_for_status()
        received = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                received += len(chunk)
                if received > MAX_ARCHIVE_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise SystemExit("Archive exceeds sanity size limit; download aborted")
                fh.write(chunk)

    checksum = sha256_file(target)
    manifest = {
        "dataset_id": dataset_id,
        "source_url": url,
        "archive_path": str(target),
        "archive_bytes": received,
        "sha256": checksum,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFEST_DIR / f"{dataset_id}_download.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Checksum: {checksum}\nManifest: {manifest_path}")
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download a registered dataset (original source only)")
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args(argv)
    load_registry()  # validates the registry before any network action
    download(args.dataset)


if __name__ == "__main__":
    main(sys.argv[1:])
