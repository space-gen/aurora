# SolarHub — Architecture

## Overview

SolarHub (codename **Aurora**) is the backend orchestration layer for the SolarHub
citizen-science platform.  It manages task data, user annotations, machine-learning pipelines,
and data synchronisation across three external platforms: **GitHub**, **HuggingFace**, and **Kaggle**.

```
┌─────────────────────────────────────────────────────────────────┐
│                         GitHub (Repo B)                         │
│                                                                 │
│  data/            ← task JSON files served to Repo A (UI)      │
│  annotations/     ← pending user annotations                   │
│  data_processing/ ← nightly pipeline workspace                 │
│  scripts/         ← Python pipeline scripts                    │
│  .github/workflows/ ← GitHub Actions orchestration             │
└───────────┬─────────────────────────┬───────────────────────────┘
            │                         │
            ▼                         ▼
 ┌──────────────────┐      ┌──────────────────────┐
 │   HuggingFace    │      │        Kaggle         │
 │  (datasets &     │      │  (training &          │
 │   models)        │◄─────│   inference kernels)  │
 └──────────────────┘      └──────────────────────┘
```

## Components

### Repo A (UI) — not in this repository
A separate frontend application that reads task files from `data/` and submits annotations
as GitHub Issues.

### GitHub Actions — `.github/workflows/`
Nine sequential workflow files execute the nightly pipeline at 00:00 UTC.  They are the
sole orchestration layer; no other scheduler is used.

### Python Scripts — `scripts/`
Modular, single-responsibility scripts invoked by the GitHub Actions workflows.

| Script | Responsibility |
|--------|----------------|
| `pull_new_urls.py` | Fetch new solar-observation URLs from official APIs |
| `merge_annotations_to_hf.py` | Push pending annotations to the HuggingFace dataset |
| `prepare_kaggle_dataset.py` | Build and upload the Kaggle training/inference dataset |
| `import_kaggle_predictions.py` | Pull prediction output from Kaggle and write it to task files |
| `compute_points.py` | Evaluate model accuracy against user annotations |

### HuggingFace
Stores the labelled annotation dataset (`SpaceGen/solarhub-annotations`) and trained models
(`SpaceGen/solarhub-model`).  Access requires the `HF_TOKEN` GitHub Actions secret.

### Kaggle
Runs training and daily inference kernels against the HuggingFace dataset.  Predictions are
pushed back to this repository as `predictions.json` using a Kaggle secret containing a
scoped GitHub token.  Access requires the `KAGGLE_USERNAME` and `KAGGLE_KEY` GitHub Actions
secrets.

## Security Model

All external service credentials are stored **exclusively** as GitHub Actions secrets:

| Secret | Used by | Purpose |
|--------|---------|---------|
| `HF_TOKEN` | `merge_annotations_to_hf.py`, `pull_new_urls.py` | HuggingFace write access |
| `KAGGLE_USERNAME` | `prepare_kaggle_dataset.py`, `import_kaggle_predictions.py` | Kaggle authentication |
| `KAGGLE_KEY` | `prepare_kaggle_dataset.py`, `import_kaggle_predictions.py` | Kaggle authentication |
| `GH_TOKEN` | Kaggle inference kernel (external) | Push predictions back to GitHub |

No credentials are ever committed to source code or configuration files.

## Design Constraints

1. No real scientific data is stored in this repository — only URLs.
2. `data_processing/` and HuggingFace datasets must never mix automatically.
3. ML training happens exclusively on Kaggle.
4. HuggingFace stores datasets and trained models only.
5. GitHub Actions is the sole workflow orchestrator.
