# Data Schema

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

SolarHub uses a standardized **JSON Lines (JSONL)** format for all solar task and annotation data.

## Format: Compressed JSONL

Every data file in the repository (under `data/` and `annotations/`) is a `.jsonl` file. Each line is a single, independent, and minified JSON object representing one solar observation record.

**Key Benefits:**
- **Git Friendly**: Append-only structure prevents merge conflicts between contributors.
- **High Compression**: Zero whitespace and minified separators for minimal file size.
- **Streaming Ready**: Optimized for machine learning pipelines (HuggingFace/Kaggle).

---

## Task Record Schema

Each task is represented as a single minified line in a `.jsonl` file.

```json
{
  "id": "sp-1234",
  "serial_number": 1234,
  "url": "http://...",
  "task_type": "sunspot",
  "created_at": "2026-03-17T00:30:00Z",
  "annotations": [
    {
      "user": "github_username",
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
| `id` | `string` | Unique identifier. |
| `serial_number` | `integer` | Incremental serial. |
| `url` | `string` | Image URL. |
| `task_type` | `string` | Scientific category. |
| `created_at` | `string` | Record creation timestamp. |
| `annotations` | `list` | **User Contributions**: Contains all user data (username, points, labels). |
| `metadata` | `object` | **System Only**: Reserved for backend metadata (source, capture date). No user information. |

---

## Annotation Entry Structure

Each entry in the `annotations` list represents a contribution from a single user. All identifying information and scientific labels must be contained here.

| Field | Type | Description |
|-------|------|-------------|
| `user` | `string` | GitHub username. |
| `locations` | `list` | Array of point/region objects. |
| `issue_number` | `integer` | Submission source issue. |
| `timestamp` | `string` | Contribution timestamp. |

### Location Object

```json
{ "x": 450, "y": 210, "radius": 15, "label": "class_f" }
```

Labels are applied to **specific locations** only. There is no image-wide label field.
