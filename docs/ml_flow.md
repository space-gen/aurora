# SolarHub Helios — ML Flow

## Overview

Machine-learning training and inference run exclusively on **Kaggle**.
HuggingFace acts as the dataset and model registry.
GitHub Actions orchestrates the trigger sequence.

```
  HuggingFace dataset           Kaggle kernel
  solarhub/helios-annotations ──► solarhub-helios-training
                                         │
                                         ▼ (trained model)
  HuggingFace model hub         solarhub/helios-model
  solarhub/helios-model ◄────────────────┘

  data_processing/ URLs ─────► solarhub-helios-inference
                                         │
                                         ▼ (predictions.json)
                               GitHub (import_kaggle_predictions.py)
```

## Training Pipeline

1. **Data source:** The `solarhub/helios-annotations` HuggingFace dataset, which is
   updated nightly by `merge_annotations_to_hf.py`.

2. **Trigger:** The `05_trigger_kaggle_training.yml` GitHub Actions workflow calls the
   Kaggle API using `KAGGLE_USERNAME` + `KAGGLE_KEY` secrets to run the
   `solarhub-helios-training` kernel.

3. **Kernel responsibilities:**
   - Pull the latest HuggingFace dataset using the `datasets` library and `HF_TOKEN`.
   - Fine-tune the solar-classification model.
   - Push the updated model to `solarhub/helios-model` on HuggingFace model hub.

4. **Output:** A versioned model artifact on HuggingFace.

## Inference Pipeline

1. **Data source:** The Kaggle dataset `solarhub-helios-dataset` (uploaded by
   `prepare_kaggle_dataset.py`) containing current solar-observation URLs.

2. **Trigger:** The `06_trigger_kaggle_inference.yml` GitHub Actions workflow calls the
   Kaggle API to run the `solarhub-helios-inference` kernel.

3. **Kernel responsibilities:**
   - Pull the latest model from `solarhub/helios-model` on HuggingFace.
   - Pull the latest task URLs from the Kaggle dataset.
   - Run inference on each observation image.
   - Produce `predictions.json` in the format:
     ```json
     {
       "https://solar-data-source/img.jpg": {
         "ml_prediction": "active_region",
         "confidence": 0.92
       }
     }
     ```
   - Push `predictions.json` back to this GitHub repository using a scoped
     `GH_TOKEN` stored as a Kaggle Secret.

4. **Output:** `predictions.json` committed to this repository (read by Stage 7).

## Supported Task Types

| Task Type | Description |
|-----------|-------------|
| `sunspot` | Classify sunspot activity regions |
| `solar_flare` | Detect and classify solar flare events |
| `magnetogram` | Classify magnetic polarity features |
| `coronal_hole` | Identify coronal holes from EUV imagery |

## Secrets Required

| Secret | Where set | Purpose |
|--------|-----------|---------|
| `HF_TOKEN` | GitHub Actions | Read/write HuggingFace datasets and models |
| `KAGGLE_USERNAME` | GitHub Actions | Kaggle API authentication |
| `KAGGLE_KEY` | GitHub Actions | Kaggle API authentication |
| `GH_TOKEN` | Kaggle Secrets | Push predictions.json back to GitHub |

## Isolation Guarantee

`data_processing/` content and HuggingFace datasets are **never mixed automatically**.
Annotation data flows from `annotations/` → HuggingFace only through the explicit
`merge_annotations_to_hf.py` script called in Stage 3.  Task processing files in
`data_processing/` are uploaded to Kaggle independently, never directly to HuggingFace.
