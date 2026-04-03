# HuggingFace Dataset Schema

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

This page defines the permanent storage schema for SolarHub datasets hosted on HuggingFace.

## Overview

The HuggingFace datasets (`SpaceGen/solarhub-*`) store the long-term history of all community-labeled solar data. Unlike the GitHub repository, which only maintains a 24-hour window, HuggingFace is an **append-only** historical archive.

## Column Definitions

| Column | Type | Description |
|--------|------|-------------|
| `id` | `string` | Unique task ID (e.g., `sp-1234`). |
| `serial_number` | `int64` | Incremental serial number. |
| `url` | `string` | Permanent URL to the solar observation image. |
| `task_type` | `string` | The scientific category (sunspot, magnetogram, etc.). |
| `created_at` | `string` | ISO-8601 timestamp of record creation. |
| `annotations` | `string (JSON)` | A JSON-serialized array of all user contributions. |
| `metadata` | `string (JSON)` | A JSON-serialized object containing capture and source metadata. |

---

## The `annotations` Column

The `annotations` column stores a full history of human labels. Because HuggingFace datasets prefer flat or simple nested structures, we store the full annotation list as a **compressed JSON string**.

### Decoded Example:
```json
[
  {
    "user": "github_user_1",
    "issue_number": 101,
    "timestamp": "2026-03-18T12:00:00Z",
    "locations": [
      { "label": "class_f", "rle": "450000 15 1009 15" }
    ]
  }
]
```

## Schema Reconciliation

The synchronization script (`merge_annotations_to_hf.py`) performs automated schema evolution. 

1. **Union Merge**: If a new version of the Aurora backend adds a field (e.g., `confidence_score`), the script identifies the missing column on HuggingFace and updates the dataset features automatically.
2. **Backward Compatibility**: All historical records are preserved. Missing fields in older records are filled with `null`.
3. **Deduplication**: Records are merged by `id`. If a record is updated with a new annotation, the new entry is appended to the existing `annotations` array for that record ID.
