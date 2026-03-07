# SolarHub — Aurora

> **Backend orchestration system for the SolarHub citizen-science platform.**

[![Nightly Pipeline](https://github.com/space-gen/aurora/actions/workflows/01_lock_and_prepare.yml/badge.svg)](https://github.com/space-gen/aurora/actions)

## Overview

This repository is **Repo B** of the SolarHub platform.  It manages task data,
user annotations, machine-learning pipelines, and synchronisation between GitHub,
HuggingFace, and Kaggle.

Repo A (the user-facing UI) is maintained separately and reads task files from
the `data/` directory of this repository.

## Repository Structure

```
aurora/
├── data/                    # Task JSON files shown to users (URLs only, no raw data)
├── data_processing/         # Nightly pipeline workspace (renamed from data/ during run)
├── annotations/             # User annotations pending HuggingFace merge
├── scripts/                 # Python pipeline scripts
│   ├── pull_new_urls.py          # Stage 2 — fetch & validate URLs (with pagination)
│   ├── merge_annotations_to_hf.py # Stage 3 — push annotations to HuggingFace
│   ├── prepare_kaggle_dataset.py  # Stage 5 — upload dataset to Kaggle
│   ├── import_kaggle_predictions.py # Stage 7 — import ML predictions
│   ├── compute_points.py          # Stage 8 — evaluate model accuracy
│   ├── parse_issue_annotation.py  # Parse GitHub issue bodies into annotation JSON
│   └── setup_platforms.py         # One-time HuggingFace + Kaggle initialisation
├── workflows/               # Nightly pipeline documentation
├── configs/                 # System configuration
├── docs/                    # Architecture, pipeline, and ML-flow docs
├── .github/ISSUE_TEMPLATE/  # GitHub issue forms for annotation submission
└── .github/workflows/       # GitHub Actions workflows (nightly pipeline + annotation)
```

## Submitting Annotations

Users annotate solar observations by **opening a GitHub Issue** using the
*Submit Solar Observation Annotation* template.  When the `annotation` label
is applied to an issue, the `00_parse_annotation_issue.yml` workflow
automatically parses the form fields and writes the annotation to
`annotations/`.  It is then merged into the HuggingFace dataset during the
next nightly pipeline run.

## First-Time Setup

Before running the nightly pipeline for the first time, initialise the
HuggingFace and Kaggle resources by triggering the **Setup Platforms**
workflow manually from the Actions tab (requires `HF_TOKEN`, `KAGGLE_USERNAME`,
and `KAGGLE_KEY` secrets to be set):

```
Actions → Setup Platforms → Run workflow → confirm: yes
```

## Nightly Pipeline

The pipeline runs every midnight UTC and progresses through 9 stages:

| Stage | Workflow | Description |
|-------|----------|-------------|
| — | `00_parse_annotation_issue.yml` | Parse issue annotations (event-driven, not nightly) |
| 1 | `01_lock_and_prepare.yml` | Rename `data/` → `data_processing/` |
| 2 | `02_refresh_data.yml` | Fetch & validate new solar-observation URLs (with pagination) |
| 3 | `03_merge_annotations.yml` | Push annotations to HuggingFace |
| 4 | `04_sync_annotations.yml` | Sync task templates into `annotations/` |
| 5 | `05_trigger_kaggle_training.yml` | Trigger Kaggle model training |
| 6 | `06_trigger_kaggle_inference.yml` | Trigger Kaggle daily inference |
| 7 | `07_import_predictions.yml` | Write ML predictions into task files |
| 8 | `08_compute_points.yml` | Evaluate model accuracy against user annotations |
| 9 | `09_unlock_frontend.yml` | Rename `data_processing/` → `data/` |

## Required Secrets

Set the following secrets under **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
|--------|---------|
| `HF_TOKEN` | HuggingFace write token (dataset + model hub access) |
| `KAGGLE_USERNAME` | Kaggle account username |
| `KAGGLE_KEY` | Kaggle API key |

The Kaggle inference kernel also requires a `GH_TOKEN` **Kaggle Secret** to push
`predictions.json` back to this repository.

## Documentation

- [Architecture](docs/architecture.md)
- [Pipeline Details](docs/pipeline.md)
- [ML Flow](docs/ml_flow.md)
- [Nightly Pipeline Docs](workflows/nightly_pipeline_docs.md)

## Design Principles

1. No real scientific data is stored here — only URLs pointing to official sources.
2. `data_processing/` and HuggingFace datasets never mix automatically.
3. ML training runs exclusively on Kaggle.
4. HuggingFace stores datasets and models.
5. GitHub Actions is the sole orchestrator.

## Supported Task Types

- `sunspot` — Sunspot activity classification
- `solar_flare` — Solar flare detection and classification
- `magnetogram` — Magnetic polarity feature classification
- `coronal_hole` — Coronal hole identification from EUV imagery
- `prominence` — Solar prominence and filament detection
- `active_region` — Active solar region identification
- `cme` — Coronal mass ejection detection

## License

See [LICENSE](LICENSE).