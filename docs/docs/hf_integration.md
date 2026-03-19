# HuggingFace Integration

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

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

Local changes from the **`annotations/`** directory are synchronized to HuggingFace during the **Nightly Pipeline**. 

> **Important**: Only records that contain actual user-submitted annotations are pushed to HuggingFace. Raw image URLs without labels remain exclusively in the GitHub repository buffer for 24 hours.

1. **Detection**: `merge_annotations_to_hf.py` identifies updated `.jsonl` files in `annotations/`.
2. **Filtering**: The script filters for records where the `annotations` list is not empty.
3. **Reconciliation**: If the local schema has new fields, the script automatically updates the HuggingFace dataset schema.
4. **Merging**: New records are **appended** to the master dataset. If a record with the same ID/URL already exists on HuggingFace, its `annotations` list is merged and deduplicated, ensuring a complete historical record.

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
