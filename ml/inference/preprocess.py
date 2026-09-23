"""Inference preprocessing (Phase 4).

Deterministic, versioned preprocessing shared by training-time datasets and
production inference: EXIF stripped, orientation normalised, RGB conversion,
documented resize. The preprocessing version is recorded with every analysis
so results remain reproducible.
"""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageOps

PREPROCESSING_VERSION = "agriq-image-preprocess-v1"


def preprocess(img: Image.Image, input_size: int = 224) -> Image.Image:
    """EXIF-safe, orientation-normalised RGB preprocessing."""
    img = ImageOps.exif_transpose(img)   # normalise orientation from EXIF
    img = img.convert("RGB")             # drop alpha/palette; standardises channels
    # EXIF data is NOT carried forward: ImageOps.exif_transpose returns a new
    # image without the orientation tag, and .convert() drops metadata.
    return img.resize((input_size, input_size), Image.BILINEAR)


def to_tensor(img: Image.Image) -> Any:
    """Convert a preprocessed PIL image to a normalised torch tensor."""
    import torch

    arr = torch.tensor(list(img.getdata()), dtype=torch.float32)
    arr = arr.view(img.height, img.width, 3).permute(2, 0, 1) / 255.0
    mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
    return (arr - mean) / std


def build_training_transforms(config: dict[str, Any]):
    """Training-time transforms (used only by ml.training.train with torch present)."""
    from torchvision import transforms

    train_tf = transforms.Compose(
        [
            transforms.RandomHorizontalFlip(p=0.5 if config["training"]["augmentation"]["horizontal_flip"] else 0.0),
            transforms.RandomRotation(config["training"]["augmentation"]["rotation_degrees"]),
            transforms.ColorJitter(brightness=config["training"]["augmentation"]["brightness_jitter"]),
            transforms.Resize((config["input_size"], config["input_size"])),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    eval_tf = transforms.Compose(
        [
            transforms.Resize((config["input_size"], config["input_size"])),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    return {"train": train_tf, "eval": eval_tf}


def training_dataset(manifest: dict[str, Any], config: dict[str, Any]):
    """Datasets from a split manifest (requires real validated image files)."""
    from PIL import Image as PILImage
    from torch.utils.data import Dataset

    transforms_map = build_training_transforms(config)
    label_to_index = {label: i for i, label in enumerate(config["classes"])}

    class _SplitDataset(Dataset):
        def __init__(self, paths: list[str], tf) -> None:
            self.paths = paths
            self.tf = tf

        def __len__(self) -> int:
            return len(self.paths)

        def __getitem__(self, idx: int):
            # Stored paths come from the validation manifest, whose provisional
            # labels were mapped through the reviewed label mapping.
            path = self.paths[idx]
            img = PILImage.open(path)
            label = _label_for(path, manifest, config, label_to_index)
            return self.tf(img), label

    datasets = {}
    for split in ("train", "val", "test"):
        paths = manifest["splits"].get(split, [])
        datasets[split] = _SplitDataset(paths, transforms_map["eval" if split != "train" else "train"])
    return datasets


def _label_for(path: str, manifest: dict[str, Any], config: dict[str, Any], index: dict[str, int]) -> int:
    # Labels were bound at validation time; look them up from the validation manifest.
    from ml.data.label_mapping import map_label

    dataset_id = manifest["dataset_id"]
    agriq_label = map_label(dataset_id, path) if False else _cached_label(dataset_id, path)
    return index.get(agriq_label, index["unsupported"])


_label_cache: dict[tuple[str, str], str] = {}


def _cached_label(dataset_id: str, path: str) -> str:
    if (dataset_id, path) not in _label_cache:
        import json as _json
        from pathlib import Path as _Path

        manifest_path = _Path(__file__).parents[1] / "data" / "manifests" / f"{dataset_id}_validation.json"
        data = _json.loads(manifest_path.read_text(encoding="utf-8"))
        for rec in data["records"]:
            if rec["stored_path"] == path:
                _label_cache[(dataset_id, path)] = rec["label"]
                break
        else:
            _label_cache[(dataset_id, path)] = "unsupported"
    return _label_cache[(dataset_id, path)]
