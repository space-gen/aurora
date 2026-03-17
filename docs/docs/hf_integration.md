# HuggingFace Integration

HuggingFace is the backbone of SolarHub's data storage. We use it both for archiving community-labeled datasets and for versioning our machine-learning models.

## Dataset Structure

Each task type in SolarHub corresponds to a separate HuggingFace dataset repository.

- **Base URL**: `https://huggingface.co/datasets/SpaceGen/`
- **Naming Convention**: `solarhub-{task-type}`
- **Examples**:
  - `solarhub-sunspot`
  - `solarhub-magnetogram`
  - `solarhub-solar-flare`

### Splits

- **`train`**: The primary split containing all community-submitted annotations and historical data.
- **`tasks`**: (Internal) Used by the pipeline to track URLs that haven't been labeled yet.

## Synchronization Workflow

Local changes from this GitHub repository are synchronized to HuggingFace during the **Nightly Pipeline**.

1. **Detection**: `merge_annotations_to_hf.py` identifies updated JSON files in `annotations/`.
2. **Reconciliation**: If the local schema has new fields (e.g., a new metadata attribute), the script automatically updates the HuggingFace dataset schema.
3. **Merging**: New records are appended, and existing records are updated using a "union merge" strategy—ensuring that data from both the GitHub user and any ML-pre-predictions are preserved.

## Model Hub

Trained model weights are stored in the HuggingFace Model Hub.

- **Naming Convention**: `solarhub-model-{task-type}`
- **Usage**: Kaggle inference kernels pull the latest model version from these repositories to generate predictions for new solar imagery.

---

## Security & Access

Interaction with HuggingFace is authenticated using the `HF_TOKEN` GitHub Actions secret.

- **Requirements**: The token must have **Write** permissions to the `SpaceGen` organization repositories.
- **Library**: We use the `huggingface_hub` and `datasets` Python libraries for all API interactions.

---

## Data Schema Evolution

SolarHub is designed for long-term scientific research. If the data schema needs to change (e.g., adding a "confidence" score to user labels), the `merge_annotations_to_hf.py` script ensures that old data remains compatible by filling new fields with `null` values for historical records.
