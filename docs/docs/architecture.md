# SolarHub — Architecture

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

## Overview

SolarHub (codename **Aurora**) is the backend orchestration layer for the SolarHub
citizen-science platform. It manages solar observation data, user annotations, 
machine-learning pipelines, and data synchronization across external platforms: 
**GitHub**, **HuggingFace**, and **Kaggle**.

```
┌─────────────────────────────────────────────────────────────────┐
│                         GitHub (Repo B)                         │
│                                                                 │
│  data/            ← active task JSON files                     │
│  annotations/     ← pending user annotations & templates       │
│  data_processing/ ← temporary nightly pipeline workspace        │
│  scripts/         ← Python automation scripts                  │
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

## Core Components

### 1. Data Hub (GitHub)
The central repository for task orchestration. It stores image URLs and serves as the bridge between citizen scientists (via GitHub Issues) and the ML pipeline.

### 2. Automation Engine (GitHub Actions)
Manages the lifecycle of data and annotations:
- **Nightly Pipeline (`pipeline.yml`)**: Daily synchronization of data with JSOC and HuggingFace.
- **Annotation Parser (`parse_annotation_issue.yml`)**: Real-time processing of user contributions from GitHub Issues.

### 3. Processing Scripts (`scripts/`)
Modular Python scripts that handle specific stages of the data lifecycle.

| Script | Responsibility |
|--------|----------------|
| `pull_new_urls.py` | Crawls JSOC/HMI for the latest solar imagery. |
| `parse_issue_annotation.py` | Extracts annotations from GitHub Issue bodies. |
| `merge_annotations_to_hf.py` | Synchronizes local annotations with HuggingFace datasets. |
| `compute_points.py` | (Work in Progress) Evaluates ML model accuracy. |

### 4. External Integrations
- **HuggingFace**: The primary storage for labeled datasets (`SpaceGen/solarhub-*`) and trained models.
- **Kaggle**: Provides the compute environment for training models and running inference on new solar data.

## Security Model

Security is maintained through GitHub Actions secrets. No credentials are stored in the codebase:

| Secret | Purpose |
|--------|---------|
| `HF_TOKEN` | Write access to HuggingFace datasets and models. |
| `KAGGLE_USERNAME` | Authentication for the Kaggle API. |
| `KAGGLE_KEY` | Authentication for the Kaggle API. |
| `GITHUB_TOKEN` | Default token for repository operations (commits/pushes). |

## Key Design Principles

1. **URL-Only Storage**: We store only the URLs to high-resolution solar data (e.g., from JSOC) to keep the repository lightweight.
2. **Schema Resilience**: `merge_annotations_to_hf.py` uses a union-schema approach to handle evolving data structures without data loss.
3. **Citizen-Science First**: The system is built to process human-labeled data from GitHub Issues as the primary source of truth for training.
