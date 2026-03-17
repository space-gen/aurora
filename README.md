# SolarHub — Aurora

> **Backend orchestration system for the SolarHub citizen-science platform.**
>
> I’m [Soumyadip Karforma](https://github.com/soumyadipkarforma), founder of SolarHub. Aurora is the backend engine I designed to run our contributor-powered solar science pipeline.

[![Nightly Pipeline](https://github.com/space-gen/aurora/actions/workflows/pipeline.yml/badge.svg)](https://github.com/space-gen/aurora/actions)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange)](https://buymeacoffee.com/soumyadipkarforma)

## Funding

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D?style=for-the-badge&logo=patreon)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/soumyadipkarforma)

## Overview

This repository is **Repo B** of the SolarHub platform. It manages task data,
user annotations, machine-learning pipelines, and synchronisation between GitHub,
HuggingFace, and Kaggle.

Repo A (the user-facing UI) is maintained separately and reads task files from
the `data/` directory of this repository.

## Tech Stack

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![GitHub Actions](https://img.shields.io/badge/github%20actions-%232671E5.svg?style=for-the-badge&logo=githubactions&logoColor=white)
![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Datasets-yellow?style=for-the-badge)
![Kaggle](https://img.shields.io/badge/Kaggle-20BEFF?style=for-the-badge&logo=Kaggle&logoColor=white)
![Docusaurus](https://img.shields.io/badge/Docusaurus-3EE6AF?style=for-the-badge&logo=docusaurus&logoColor=white)
![JSON](https://img.shields.io/badge/json-5E5E5E?style=for-the-badge&logo=json&logoColor=white)

## Repository Structure

```
aurora/
├── data/                    # Active task JSON files (URLs only, no raw data)
├── data_processing/         # Temporary nightly pipeline workspace
├── annotations/             # User annotations pending HuggingFace merge
├── scripts/                 # Python pipeline scripts
│   ├── pull_new_urls.py          # Daily solar data crawler
│   ├── merge_annotations_to_hf.py # Push annotations to HuggingFace (Schema reconciled)
│   ├── parse_issue_annotation.py  # Parse GitHub issue bodies into annotation JSON
│   ├── compute_points.py          # Evaluate model accuracy
│   └── setup_platforms.py         # One-time HuggingFace + Kaggle initialisation
├── configs/                 # System configuration (YAML)
├── docs/                    # Docusaurus documentation source
├── .github/ISSUE_TEMPLATE/  # GitHub issue forms for annotation submission
└── .github/workflows/       # GitHub Actions (Pipeline, Parser, Docs Deploy)
```

## Data Schema

Each task record includes:
- `user_label`: Human-provided classification.
- `ml_label`: Machine-learning model prediction.
- `locations`: Array of coordinate objects `{x, y, radius, label}`.

## Submitting Annotations

Users annotate solar observations by **opening a GitHub Issue** using the
*Submit Solar Observation Annotation* template. When the `annotation` label
is applied, the `Parse Annotation Issue` workflow automatically parses the 
form and writes it to `annotations/`. It is merged into HuggingFace during 
the next nightly pipeline run.

## Nightly Pipeline

The pipeline runs daily at **00:30 UTC** and follows a 4-stage parallel architecture:

| Stage | Workflow | Description |
|-------|----------|-------------|
| 1 | `Stage 01 · Lock Frontend` | Renames `data/` → `data_processing/` to prevent UI inconsistency. |
| 2A | `Node A · Pull New URLs` | Fetches new solar-observation URLs from JSOC. |
| 2B | `Node B · Push Annotations to HF` | Merges pending user annotations to HuggingFace datasets. |
| 4 | `Stage 04-05 · Sync & Unlock` | Syncs templates, renames `data_processing/` → `data/`. |

## Documentation

Comprehensive documentation is available at [space-gen.github.io/aurora/](https://space-gen.github.io/aurora/):

- [Architecture](https://space-gen.github.io/aurora/architecture)
- [Pipeline Details](https://space-gen.github.io/aurora/pipeline)
- [ML Flow](https://space-gen.github.io/aurora/ml_flow)
- [Data Schema](https://space-gen.github.io/aurora/data_schema)

## Required Secrets

| Secret | Purpose |
|--------|---------|
| `HF_TOKEN` | HuggingFace write token |
| `KAGGLE_USERNAME` | Kaggle API authentication |
| `KAGGLE_KEY` | Kaggle API authentication |

## License

See [LICENSE](LICENSE).
