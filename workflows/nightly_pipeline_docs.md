# Nightly Pipeline Documentation

## Purpose

This document describes the nightly automation pipeline for SolarHub Helios (Aurora).
The pipeline runs every day at **00:00 UTC** and is fully orchestrated by GitHub Actions.

## Workflow Files

| File | Stage | Description |
|------|-------|-------------|
| `01_lock_and_prepare.yml` | 1 | Rename `data/` → `data_processing/` (system lock) |
| `02_refresh_data.yml` | 2 | Fetch new solar-observation URLs |
| `03_merge_annotations.yml` | 3 | Push annotations to HuggingFace |
| `04_sync_annotations.yml` | 4 | Copy task templates into `annotations/` |
| `05_trigger_kaggle_training.yml` | 5 | Trigger Kaggle model training |
| `06_trigger_kaggle_inference.yml` | 6 | Trigger Kaggle daily inference |
| `07_import_predictions.yml` | 7 | Import ML predictions into task files |
| `08_compute_points.yml` | 8 | Score user annotations vs. ML predictions |
| `09_unlock_frontend.yml` | 9 | Rename `data_processing/` → `data/` (unlock) |

## Required GitHub Actions Secrets

| Secret Name | Description |
|-------------|-------------|
| `HF_TOKEN` | HuggingFace API write token |
| `KAGGLE_USERNAME` | Kaggle account username |
| `KAGGLE_KEY` | Kaggle API key |

Set these secrets in your repository under **Settings → Secrets and variables → Actions**.

## Failure Behaviour

If any workflow stage fails, all downstream stages are skipped automatically (each
workflow uses `on: workflow_run` with a success-check guard).  The system remains in
"locked" state (`data_processing/` exists instead of `data/`) until the pipeline is
re-run successfully or an operator manually renames the directory.

## Manual Re-run

To re-run the pipeline from a specific stage, trigger the corresponding workflow
manually from the **Actions** tab using `workflow_dispatch`.
