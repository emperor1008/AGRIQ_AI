# Crop-Image Intelligence (Phase 4)

Validated crop-image screening for **rice** and **tomato** leaves, integrated
with the Phase 2 Farm Copilot's safety guardrails.

## Honest current status

**No model has been registered as approved for production.** Until a real
model passes the full dataset → training → calibration → evaluation →
approval pipeline, every image-analysis request returns:

> "Image analysis is not currently available."

This is a *correct outcome*, not a failure. Nothing is fabricated: no
predictions, no confidence values, no metrics. The registry
(`ml/models/registry.yaml`) ships empty and can only be filled by a named
human approver after real evaluation.

## Supported scope (only this, nothing more)

| Crop   | Classes |
|--------|---------|
| Rice   | healthy, blast, bacterial leaf blight, brown spot, (tungro only if a sufficiently validated dataset supports it), unsupported/unknown |
| Tomato | healthy, early blight, late blight, (leaf-mould/leaf-curl only when dataset labels + validation support them), unsupported/unknown |

Any other crop returns: *"This crop is not supported by the current
validated model."*

## Architecture

```
Upload → decoded-format verification (never trust MIME/extension)
       → decompression-bomb guard, size/dimension limits
       → EXIF-stripped, orientation-normalised processed copy
         (original preserved untouched in private storage)
       → quality gate (dark / overexposed / blurry / too small / non-leaf)
         with actionable retake guidance
       → crop routing (farmer-declared + consistency check)
       → registry-approved model ONLY (checksum verified, fail-closed)
       → abstention policy (low confidence, close top-2, OOD, mismatch)
       → "possible condition" result — never "confirmed disease"
       → Phase 2 Copilot + safety guardrails for any recommendation
```

Key modules:

- `ml/inference/registry.py` — approved-model + checksum gating
- `ml/inference/quality.py` — quality gate with retake guidance
- `ml/inference/abstention.py` — documented refusal reasons
- `ml/inference/predictor.py` — fail-closed analysis entry point
- `agriq/services/image_service.py` — storage, validation, persistence
- `agriq/api/images.py` — HTTP layer (no ML logic in routes)

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/v1/crop-images/capabilities` | honest availability probe |
| POST   | `/api/v1/crop-images/analyse` | upload + screen one image |
| GET    | `/api/v1/crop-images/analyses/{id}` | owned detail |
| DELETE | `/api/v1/crop-images/analyses/{id}` | soft delete (history kept) |
| POST   | `/api/v1/crop-images/analyses/{id}/feedback` | farmer feedback (never an expert label) |
| POST   | `/api/v1/crop-images/analyses/{id}/request-expert-review` | escalate to expert workflow |

All routes are authenticated; a foreign analysis reads as 404.

## Safety rules

1. Raw softmax is never shown to farmers. Confidence categories
   (insufficient evidence / low / moderate / higher) exist only after
   calibration is registered.
2. Abstention is a correct outcome; the reason is recorded and shown.
3. Image output alone can never produce a pesticide/fertiliser dosage.
   Recommendations flow through the Copilot with approved knowledge
   retrieval and chemical-safety guardrails.
4. Every result carries "Image screening cannot confirm a laboratory
   diagnosis" and expert confirmation is required by default.
5. Grad-CAM / attention overlays are not implemented in Phase 4; when they
   are, they will be labelled as model attention, not biological proof.

## Data provenance and storage

- Originals and processed copies live in **private storage**
  (`IMAGE_STORAGE_PATH`, random server-side names), never under the public
  static tree, never exposed by a URL.
- Only JPEG/PNG/WebP are accepted; format is verified from decoded content.
- Farmer feedback and expert labels are stored in separate columns; one is
  never treated as the other.

## Evaluation status

**Not yet validated.** Until real evaluation happens:

- No accuracy/precision/recall/F1 numbers are displayed anywhere.
- The UI shows "Model validation for local field conditions is in progress."
- The full pipeline (dataset registry → leakage-checked splits → training →
  calibration → external-field evaluation → named approval) is documented in
  `ml/README.md` and must be completed before any model is registered.
