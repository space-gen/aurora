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
user annotations, solar observation data pipelines, and synchronisation between GitHub
and HuggingFace.

Repo A (the user-facing UI) is maintained separately and reads task files from
the `data/` directory of this repository.

## Tech Stack

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![GitHub Actions](https://img.shields.io/badge/github%20actions-%232671E5.svg?style=for-the-badge&logo=githubactions&logoColor=white)
![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Datasets-yellow?style=for-the-badge)
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
│   └── setup_platforms.py         # One-time HuggingFace initialisation
├── configs/                 # System configuration (YAML)
├── docs/                    # Docusaurus documentation source
├── .github/ISSUE_TEMPLATE/  # GitHub issue forms for annotation submission
└── .github/workflows/       # GitHub Actions (Pipeline, Parser, Docs Deploy)
```

## Data Schema

The data is stored in a compressed JSON Lines (JSONL) format. Each line is a minified JSON object representing a solar observation record.

**Field Order:** `id`, `url`, `task_type`, `created_at`, `metadata`, `annotations`.

### Task Record Example:
```json
{
  "id": "sp-1234",
  "url": "http://...",
  "task_type": "sunspot",
  "created_at": "2026-03-17T00:30:00Z",
  "metadata": {
    "source": "JSOC_HMI_JPG",
    "captured_at": "2026-03-16"
  },
  "annotations": [
    {
      "user": "github_username",
      "locations": [
        { "x": 450, "y": 210, "radius": 15, "label": "class_f" }
      ],
      "issue_number": 42,
      "timestamp": "2026-03-17T14:30:00Z",
      "confidence_score": 95.0
    }
  ]
}
```

## Submitting Annotations

Users annotate solar observations by **opening a GitHub Issue** using the *Submit Solar Observation Annotation* template. When the `annotation` label is applied to an issue, the `Parse Annotation Issue` workflow automatically parses the form fields and writes the annotation to `annotations/`. It is merged into HuggingFace during the next nightly pipeline run.

**When submitting annotations:**
*   Use the `your_label` field to specify the scientific classification (e.g., `class_a`, `beta-gamma`, `polar`). This label will be applied to *all* coordinates provided in that submission.
*   Provide pixel coordinates in the format `x,y,radius,label`. Multiple features should be separated by a semicolon (`;`). Example: `450,320,15,active_region ; 890,110,10,quiet_sun`.

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

## Supported Task Types

SolarHub supports rigorous scientific standards for ML training:

| Task Type | Scientific Standard |
|-----------|---------------------|
| `sunspot` | **McIntosh** |
| `solar_flare` | **GOES X-ray** |
| `magnetogram` | **Mount Wilson** |
| `coronal_hole` | **Latitude** |
| `prominence` | **Behavioral** |
| `cme` | **CDAW** |

## License

See [LICENSE](LICENSE).
