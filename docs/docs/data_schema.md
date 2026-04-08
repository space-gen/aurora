# Data Schema

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

SolarHub uses a standardized **JSON Lines (JSONL)** format for all solar task and annotation data.

## Format: Compressed JSONL

Every data file in the repository (under `data/` and `annotations/`) is a `.jsonl` file. Each line is a single, independent, and minified JSON object representing one solar observation record.

---

## Task Record Schema

Each task is represented as a single minified line in a `.jsonl` file, with fields ordered as follows: `id`, `url`, `task_type`, `created_at`, `metadata`, `annotations`.

```json
{
  "id": "sp-1234",
  "url": "http://jsoc.stanford.edu/data/hmi/images/2026/03/16/000000_Ic_1k.jpg",
  "task_type": "sunspot",
  "created_at": "2026-03-17T00:30:00Z",
  "metadata": {
    "source": "JSOC_HMI_JPG",
    "captured_at": "2026-03-16"
  },
  "annotations": [
    {
      "user": "github_username",
      "confidence_score": 95.0,
      "locations": [
        { "label": "class_f", "region": "450000 15 1009 15" }
      ],
      "issue_number": 42,
      "timestamp": "2026-03-17T14:30:00Z"
    }
  ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | **Primary Key**: Unique global identifier (e.g., `sp-94`, `mg-102`). Persists across years of data. |
| `url` | `string` | Direct link to the solar observation image. |
| `task_type` | `string` | Scientific category (sunspot, magnetogram, etc.). |
| `created_at` | `string` | Record creation timestamp (ISO 8601). |
| `metadata` | `object` | **System Only**: Reserved for backend metadata (source, capture date). |
| `annotations` | `list` | A list of user annotation entries. Each entry contains `user`, `confidence_score`, `locations`, `issue_number`, and `timestamp`. |

---

## Annotation Entry Structure

Each entry in the `annotations` list represents a contribution from a single user.

| Field | Type | Description |
|-------|------|-------------|
| `user` | `string` | GitHub username. |
| `confidence_score` | `float` | Contributor's self-reported confidence (0-100). |
| `locations` | `list` | Array of point/region objects. |
| `issue_number` | `integer` | Submission source issue. |
| `timestamp` | `string` | Contribution timestamp. |

### Location Object

```json
{ "label": "class_f", "region": "450000 15 1009 15" }
```

Labels are applied to **specific regions** via the `region` field.
The parser stores each region payload exactly as submitted by the contributor (no transformation).
This means the value may contain RLE, polygon coordinates, circles, or any other accepted task-specific encoding.
There is no image-wide label field.

## Contribution Constraint

For each record `id`, a given GitHub `user` can appear at most once in `annotations`.
If the same user tries to submit another annotation for the same record, the parser rejects it and returns an error.

