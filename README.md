# SolarHub — Aurora

> **Backend orchestration system for the SolarHub citizen-science platform.**
>
> I’m [Soumyadip Karforma](https://github.com/soumyadipkarforma), founder of SolarHub. Aurora is the backend engine I designed to run our contributor-powered solar science pipeline.

[![Nightly Pipeline](https://github.com/space-gen/aurora/actions/workflows/01_lock_and_prepare.yml/badge.svg)](https://github.com/space-gen/aurora/actions)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4)](https://github.com/sponsors/soumyadipkarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange)](https://buymeacoffee.com/soumyadipkarforma)

## Funding

- GitHub Sponsors: https://github.com/sponsors/soumyadipkarforma
- Buy Me a Coffee: https://buymeacoffee.com/soumyadipkarforma

## Overview

This repository is **Repo B** of the SolarHub platform.  It manages task data,
user annotations, machine-learning pipelines, and synchronisation between GitHub,
HuggingFace, and Kaggle.

Repo A (the user-facing UI) is maintained separately and reads task files from
the `data/` directory of this repository.

## Tech Stack

- **Language:** Python 3.11 (automation scripts)
- **Orchestration:** GitHub Actions
- **Data + Model Hub:** HuggingFace (`spacegen` organization)
- **Training/Inference Compute:** Kaggle kernels
- **Documentation Portal:** Docusaurus (under `/docs`, deployed to GitHub Pages `/docs`)
- **Interfaces:** GitHub Issue Forms + JSON task files

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
`annotations/`.  It is then merged into the appropriate per-task-type
HuggingFace dataset during the next nightly pipeline run.

## First-Time Setup

Before running the nightly pipeline for the first time, initialise the
HuggingFace resources and verify Kaggle credentials by triggering the
**Setup Platforms** workflow manually from the Actions tab (requires
`HF_TOKEN`, `KAGGLE_USERNAME`, and `KAGGLE_KEY` secrets to be set):

```
Actions → Setup Platforms → Run workflow → confirm: yes
```

This creates **one HuggingFace annotation dataset and one HuggingFace model
repository per task type** (14 repos total). No data is stored in Kaggle —
Kaggle is used only for running training and inference kernels.

| Task Type | HF Annotation Dataset | HF Model Repo |
|-----------|----------------------|---------------|
| sunspot | `SpaceGen/solarhub-sunspot` | `SpaceGen/solarhub-model-sunspot` |
| solar_flare | `SpaceGen/solarhub-solar-flare` | `SpaceGen/solarhub-model-solar-flare` |
| magnetogram | `SpaceGen/solarhub-magnetogram` | `SpaceGen/solarhub-model-magnetogram` |
| coronal_hole | `SpaceGen/solarhub-coronal-hole` | `SpaceGen/solarhub-model-coronal-hole` |
| prominence | `SpaceGen/solarhub-prominence` | `SpaceGen/solarhub-model-prominence` |
| active_region | `SpaceGen/solarhub-active-region` | `SpaceGen/solarhub-model-active-region` |
| cme | `SpaceGen/solarhub-cme` | `SpaceGen/solarhub-model-cme` |

> **Important:** After setup, configure the Kaggle training kernel with an
> `HF_TOKEN` [Kaggle Secret](https://www.kaggle.com/docs/notebooks#the-secret-manager)
> so that it can push trained model weights directly to the HuggingFace model
> repos after each nightly training run.

## Nightly Pipeline

The pipeline runs every midnight UTC and progresses through 9 stages:

| Stage | Workflow | Description |
|-------|----------|-------------|
| — | `00_parse_annotation_issue.yml` | Parse issue annotations (event-driven, not nightly) |
| 1 | `01_lock_and_prepare.yml` | Rename `data/` → `data_processing/` |
| 2 | `02_refresh_data.yml` | Fetch & validate new solar-observation URLs (with pagination) |
| 3 | `03_merge_annotations.yml` | Push annotations to per-task HuggingFace datasets |
| 4 | `04_sync_annotations.yml` | Sync task templates into `annotations/` |
| 5 | `05_trigger_kaggle_training.yml` | Push task data to HuggingFace; trigger Kaggle training kernel (kernel pushes model to HF) |
| 6 | `06_trigger_kaggle_inference.yml` | Trigger Kaggle inference kernel (reads data + model from HF) |
| 7 | `07_import_predictions.yml` | Download predictions from Kaggle kernel output; update task files |
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

- [Docusaurus Docs Source](docs/)
- [Architecture](docs/docs/architecture.md)
- [Pipeline Details](docs/docs/pipeline.md)
- [ML Flow](docs/docs/ml_flow.md)
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
