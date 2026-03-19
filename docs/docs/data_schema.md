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

A single line in a `.jsonl` file looks like this (pretty-printed here for readability):

```json
{
  "id": "sp-1234",
  "serial_number": 1234,
  "url": "http://jsoc.stanford.edu/data/hmi/images/2026/03/16/000000_Ic_1k.jpg",
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
| `id` | `string` | Unique identifier (e.g., `sp-` prefix for sunspots). |
| `serial_number` | `integer` | Global incrementing number for the task type. |
| `url` | `string` | Direct link to the solar observation image. |
| `task_type` | `string` | One of `sunspot`, `magnetogram`, `solar_flare`, etc. |
| `created_at` | `string` | ISO-8601 timestamp when the record was created. |
| `annotations` | `list` | A list of user annotation entries (history). |
| `metadata` | `object` | Contextual information like capture date and source API. |

---

## Annotation Entry Structure

Each entry in the `annotations` list represents a contribution from a single user:

| Field | Type | Description |
|-------|------|-------------|
| `user` | `string` | GitHub username of the contributor. |
| `locations` | `list` | Array of coordinate objects (points or regions). |
| `issue_number` | `integer` | The GitHub Issue ID used for submission. |
| `timestamp` | `string` | ISO-8601 timestamp of the contribution. |

### Location Object

```json
{ "x": 450, "y": 210, "radius": 15, "label": "class_f" }
```

- **`x`, `y`**: Pixel coordinates relative to the 1024x1024 source image.
- **`radius`**: The radius (in pixels) of the identified feature (0 for a single point).
- **`label`**: The specific scientific classification label for this location.
