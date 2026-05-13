# SolarHub — Aurora

> **Backend orchestration system for the SolarHub citizen-science platform.**
>
> I’m [Soumyadip Karforma](https://github.com/soumyadipkarforma), founder of SpaceGen, the mother organisation of SolarHub. Aurora is the backend engine I designed to run our contributor-powered solar science pipeline.

[![Nightly Pipeline](https://github.com/space-gen/aurora/actions/workflows/pipeline.yml/badge.svg)](https://github.com/space-gen/aurora/actions)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange)](https://buymeacoffee.com/soumyadipkarforma)

## Overview

This repository is **Repo B** of the SolarHub platform. It manages task data,
user annotations, solar observation data pipelines, and synchronisation between GitHub
and HuggingFace.

Repo A (the user-facing UI : [solarhub](https://github.com/space-gen/solarhub) ) is maintained separately and reads task files from this repository. Daily pipeline writes and annotation commits now run against the dedicated orphan `data` branch, and that branch is recreated regularly to keep history minimal.

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
```jsonl
{"id":"mg-1428","url":"http://jsoc1.stanford.edu/data/hmi/images/2026/04/01/20260401_000000_M_1k.jpg","task_type":"magnetogram","created_at":"2026-04-02T00:02:08.160034+00:00","metadata":{"source":"JSOC_HMI_JPG","captured_at":"2026-04-01T00:00:00Z"},"annotations":[]}
```

## Submitting Annotations

Users annotate solar observations by **opening a GitHub Issue** using the *Submit Solar Observation Annotation* template. When the `annotation` label is applied to an issue, the `Parse Annotation Issue` workflow automatically parses the form fields and writes the annotation to `annotations/`. It is merged into HuggingFace during the next nightly pipeline run.

**When submitting annotations:**
*   Use the `your_label` field to submit one or more annotations in the format `label,region`. Multiple annotations are separated by a semicolon (`;`). Example: `class_a,10 1 5 2 3 ; class_h,2 7 1 4`.
*   Labels must be valid for the selected Task Type (see table above). The `region` payload is stored exactly as submitted.
*   A single GitHub username can annotate a given record ID only once. Repeat submissions for the same `id` by the same user are rejected by the parser.

## Documentation

Comprehensive documentation is available at [Aurora Docs](https://space-gen.github.io/aurora/):

- [Architecture](https://space-gen.github.io/aurora/architecture)
- [Pipeline Details](https://space-gen.github.io/aurora/pipeline)
- [ML Flow](https://space-gen.github.io/aurora/ml_flow)
- [Data Schema](https://space-gen.github.io/aurora/data_schema)


## Supported Task Types

SolarHub supports rigorous scientific standards for ML training:

| Task Type | Scientific Standard |
|-----------|---------------------|
| `sunspot` | **McIntosh** |
| `magnetogram` | **Mount Wilson** |
| `aia_94`, `aia_131`, `aia_171`, `aia_193`, `aia_211`, `aia_304`, `aia_335`, `aia_1600`, `aia_1700`, `aia_4500` | **NOAA SRS Hale** |

## Funding

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D?style=for-the-badge&logo=patreon)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/soumyadipkarforma)

## License

See [LICENSE](LICENSE).
