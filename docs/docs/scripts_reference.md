# Scripts Reference

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

The `scripts/` directory contains modular Python automation that powers the SolarHub data lifecycle.

---

## 1. `pull_new_urls.py`

**Purpose**: Fetches the previous day's solar imagery URLs from the JSOC/HMI API.

- **Operation**: Crawls http://jsoc.stanford.edu/ and filters for `_Ic_1k.jpg` (sunspots) and `_M_1k.jpg` (magnetograms).
- **Output**: Generates JSON task files in `data_processing/`.
- **Key Features**:
  - Automatically handles serial number incrementing for unique task IDs.
  - Prevents duplicates by checking existing URLs in the HuggingFace dataset (requires `HF_TOKEN`).

---

## 2. `parse_issue_annotation.py`

**Purpose**: Extracts user-submitted annotations from GitHub Issue bodies.

- **Trigger**: Invoked by the `Parse Annotation Issue` GitHub Actions workflow.
- **Workflow**: 
  1. Parses Markdown headers (e.g., `### Task Type`) into structured data.
  2. Validates task IDs and labels against a whitelist.
  3. Merges coordinates into the corresponding task file in `annotations/`.
- **Environment Variables**: Requires `ISSUE_NUMBER`, `ISSUE_BODY`, and `ISSUE_AUTHOR`.

---

## 3. `merge_annotations_to_hf.py`

**Purpose**: Synchronizes local `annotations/` data with HuggingFace datasets.

- **Mechanism**: Non-destructive schema reconciliation.
- **Algorithm**:
  - **Reconciliation**: If the local schema differs from the HuggingFace schema, it performs a "union merge," filling missing fields with `null`.
  - **De-duplication**: Merges records by ID/URL, ensuring that the latest data from GitHub wins on collision.
- **Library**: Built on top of the `datasets` and `huggingface_hub` libraries.

---

## 4. `compute_points.py`

**Purpose**: (Work in Progress) Evaluates machine learning model accuracy.

- **Responsibility**: Compares the latest label from `annotations` (ground truth) against `ml_label` (model output) for all labeled records.
- **Metric**: Computes overall accuracy and per-task-type performance.
- **Output**: Writes a summary report used for model auditing and progress tracking.

---

## 5. `setup_platforms.py`

**Purpose**: Initializes external platform integrations.

- **Usage**: Typically used during the initial repository setup.
- **Functions**: Sets up HuggingFace repositories and Kaggle environment variables.

---

## Development Guidelines

- **Environment**: All scripts are designed for **Python 3.11+**.
- **Dependencies**: Key libraries include `requests`, `huggingface_hub`, and `datasets`.
- **Logging**: All scripts use standard Python logging with a consistent format for easy debugging via GitHub Actions logs.
