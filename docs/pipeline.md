# SolarHub — Nightly Pipeline

## Schedule

The nightly pipeline runs every day at **00:00 UTC** via GitHub Actions scheduled triggers.

## Pipeline Stages

```
Stage 1  Lock & Prepare       rename data/ → data_processing/
Stage 2  Refresh Data         fetch new solar-observation URLs
Stage 3  Merge Annotations    push annotations → HuggingFace
Stage 4  Sync Annotation Templates  copy data_processing/ → annotations/
Stage 5  Trigger Kaggle Training    run HF dataset training kernel
Stage 6  Trigger Kaggle Inference   run daily inference kernel
Stage 7  Import Predictions    write ML results → data_processing/ task files
Stage 8  Evaluate Model Accuracy  compare ML predictions vs. user annotations
Stage 9  Unlock Frontend       rename data_processing/ → data/
```

## Stage Details

### Stage 1 — Lock & Prepare (`01_lock_and_prepare.yml`)

- Renames `data/` to `data_processing/` using a `git mv` operation.
- This prevents the frontend from reading partially-updated task files.
- The rename is committed and pushed so subsequent workflow jobs see the updated state.

### Stage 2 — Refresh Data (`02_refresh_data.yml`)

- Calls `scripts/pull_new_urls.py`.
- Fetches new solar-observation image URLs from official source APIs
  (NASA SDAC, SOHO LASCO, SDO HMI).
- Writes new task JSON files into `data_processing/`.
- Uses `HF_TOKEN` to check for duplicate URLs already in the HuggingFace dataset.

### Stage 3 — Merge Annotations (`03_merge_annotations.yml`)

- Calls `scripts/merge_annotations_to_hf.py`.
- Reads pending annotation files from `annotations/`.
- Appends them to the `SpaceGen/solarhub-annotations` HuggingFace dataset.
- Clears annotation file contents after a successful merge.
- **Requires secret:** `HF_TOKEN`

### Stage 4 — Sync Annotation Templates (`04_sync_annotations.yml`)

- Copies the current task files from `data_processing/` into `annotations/`
  as blank annotation templates.
- Users fill these templates when submitting GitHub Issues.

### Stage 5 — Trigger Kaggle Training (`05_trigger_kaggle_training.yml`)

- Calls `scripts/prepare_kaggle_dataset.py` to push updated task URLs to Kaggle.
- Triggers the `solarhub-training` Kaggle kernel via the Kaggle API.
- **Requires secrets:** `KAGGLE_USERNAME`, `KAGGLE_KEY`

### Stage 6 — Trigger Kaggle Inference (`06_trigger_kaggle_inference.yml`)

- Triggers the `solarhub-inference` Kaggle kernel via the Kaggle API.
- The inference kernel reads from HuggingFace + Kaggle dataset, runs predictions,
  and pushes `predictions.json` back to this repository.
- **Requires secrets:** `KAGGLE_USERNAME`, `KAGGLE_KEY`

### Stage 7 — Import Predictions (`07_import_predictions.yml`)

- Calls `scripts/import_kaggle_predictions.py`.
- Downloads `predictions.json` from the Kaggle kernel output.
- Writes `ml_prediction` and `confidence` values into matching task files
  in `data_processing/`.
- **Requires secrets:** `KAGGLE_USERNAME`, `KAGGLE_KEY`

### Stage 8 — Evaluate Model Accuracy (`08_compute_points.yml`)

- Calls `scripts/compute_points.py`.
- Compares ML prediction labels against user annotation labels.
- Computes overall and per-task-type model accuracy.
- Writes the accuracy report to `data_processing/model_accuracy.json`.

### Stage 9 — Unlock Frontend (`09_unlock_frontend.yml`)

- Renames `data_processing/` back to `data/`.
- Commits and pushes the final state, making updated task files available
  to Repo A (UI).

## Error Handling

- Each stage is an independent GitHub Actions workflow triggered by the
  successful completion of the previous stage (`workflow_run` trigger).
- If any stage fails, subsequent stages are not triggered, preventing
  partial updates from reaching the frontend.
- The `data/` directory remains unavailable (as `data_processing/`) until
  Stage 9 completes successfully.

## Dependencies Between Stages

```
01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09
```

Each workflow uses `on: workflow_run` with `types: [completed]` and checks
`github.event.workflow_run.conclusion == 'success'` before proceeding.
