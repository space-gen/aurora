# Data Schema

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

SolarHub uses a standardized **JSON Lines (JSONL)** format for all solar task and annotation data.

## Format: Compressed JSONL

Every data file in the repository (under `data/` and `annotations/`) is a `.jsonl` file. Each line is a single, independent, and minified JSON object representing one solar observation record.

---

## Task Record Schema

Each task is represented as a single minified line in a `.jsonl` file.

```json
{
  "id": "sp-1234",
  "url": "http://...",
  "task_type": "sunspot",
  "created_at": "2026-03-17T00:30:00Z",
  "annotations": [
    {
      "user": "github_username",
      "confidence_score": 95.0,
      "locations": [
        { "x": 450, "y": 210, "radius": 15, "label": "class_f" }
      ],
      "issue_number": 42,
      "timestamp": "2026-03-17T14:30:00Z"
    }
  ],
  "metadata": {
    "source": "JSOC_HMI_JPG",
    "captured_at": "2026-03-16"
  }
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | **Primary Key**: Unique global identifier (e.g., `sp-94`, `mg-102`). Persists across years of data. |
| `url` | `string` | Image URL. |
| `task_type` | `string` | Scientific category (sunspot, magnetogram, etc.). |
| `created_at` | `string` | Record creation timestamp. |
| `annotations` | `list` | **User Contributions**: Contains all user data (username, points, labels, confidence). |
| `metadata` | `object` | **System Only**: Reserved for backend metadata (source, capture date). |

---

## Persistence and Merging

The system prioritizes the **`id`** field for all synchronization operations.

1. **Crawler**: Generates new IDs by continuing the sequence from the last known ID in the master HuggingFace dataset.
2. **Synchronization**: When syncing to HuggingFace, if an `id` already exists, the new annotations are merged into that specific row. If the `id` is new, it is appended as a fresh row.
3. **Repository Window**: The GitHub repository only stores the most recent 24 hours of data. The full historical archive is maintained on HuggingFace.
