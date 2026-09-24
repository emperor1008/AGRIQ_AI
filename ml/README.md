# AGRIQ AI — Machine-Learning Workspace (Phase 4)

This directory holds the **crop-image intelligence** pipeline: dataset registry,
ingestion, training, evaluation, calibration, export and the lightweight
inference package consumed by the web application.

## Hard policy

- **No fabricated data.** Every dataset, checksum, metric and licence entry
  records a real, verifiable source. Until real datasets are ingested, licence-
  reviewed and approved, the registry contains **discovered entries only** and
  the web feature reports: *"Image analysis is not currently available."*
- **Only approved datasets train models** (`status: approved` in
  `data/dataset_registry.yaml` — requires licence verification and quality
  review).
- **No auto-training.** Nothing in `training/` runs at web-app start; the API
  server never imports training dependencies.
- **Abstention is correct behaviour.** The inference package refuses to
  classify images that fail quality gates, fall outside the training
  distribution, or come from unsupported crops.

## Layout

```
ml/
├── configs/            rice_classifier.yaml, tomato_classifier.yaml
├── data/
│   ├── dataset_registry.yaml   versioned dataset registry (statuses)
│   ├── label_mappings/         dataset-label → AGRIQ-label mapping (reviewed)
│   ├── manifests/              machine-readable ingestion manifests
│   ├── raw/                    immutable originals (never edited)
│   ├── validated/              checksummed, deduplicated, validated images
│   ├── quarantined/            rejected files + machine-readable rejection reports
│   ├── splits/                 split manifests with leakage checks
│   └── download.py             python -m ml.data.download --dataset ID
├── training/           train.py, evaluate.py, calibrate.py, export.py (manual run only)
├── evaluation/         metrics.py, robustness.py, subgroup_analysis.py, reports/
├── models/
│   └── registry.yaml   production model registry — web loads only approved_for_production: true
├── inference/          preprocess.py, predictor.py, quality.py, abstention.py, explanations.py
└── README.md
```

## Commands

```bash
python -m ml.data.download --dataset DATASET_ID     # original source only, checksummed
python -m ml.data.validate   --dataset DATASET_ID   # corruption/duplicate/quality validation
python -m ml.data.build_splits --dataset DATASET_ID # grouped splits, leakage-checked
python -m ml.data.report     --dataset DATASET_ID   # human + machine-readable reports
```

## Supported scope (initial)

Rice: healthy, rice blast, bacterial leaf blight, brown spot, unsupported/unknown.
Tomato: healthy, early blight, late blight, unsupported/unknown.
(Additional classes only with validated data and expert labels.)

## Status

No model is approved for production yet; the web feature shows the honest
unavailable state. Field validation for Odisha conditions has not been
performed; the UI states: *"Model validation for local field conditions is in
progress."*
