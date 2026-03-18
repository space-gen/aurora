# Data Schema

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

SolarHub uses a standardized JSON format for all solar task and annotation data. This ensures compatibility across GitHub, HuggingFace, and the frontend UI.

## Task Record Schema

Each task (e.g., a sunspot or magnetogram image) is represented as a JSON object within a list.

```json
{
  "id": "sp-1234",
  "serial_number": 1234,
  "url": "http://jsoc.stanford.edu/data/hmi/images/2026/03/16/000000_Ic_1k.jpg",
  "task_type": "sunspot",
  "user_label": null,
  "ml_label": null,
  "locations": [],
  "annotations": [],
  "metadata": {
    "source": "JSOC_HMI_JPG",
    "captured_at": "2026-03-16"
  }
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Unique identifier (e.g., `mg-` prefix for magnetograms). |
| `serial_number` | `integer` | Global incrementing number for the task type. |
| `url` | `string` | Direct link to the solar observation image. |
| `task_type` | `string` | One of `sunspot`, `magnetogram`, `solar_flare`, etc. |
| `user_label` | `string` | The latest classification label (consensus/most recent). |
| `ml_label` | `string` | The classification label assigned by the ML model. |
| `locations` | `list` | The latest list of coordinate objects. |
| `annotations` | `list` | Full history of all user contributions (label, locations, author). |
| `metadata` | `object` | Contextual information like capture date and source API. |

---

## Annotation Schema

When a user submits an annotation via a GitHub Issue, it is parsed and merged into the task record.

### Location Object

```json
{
  "x": 450,
  "y": 210,
  "radius": 15,
  "label": "active_region"
}
```

- **`x`, `y`**: Pixel coordinates relative to the 1024x1024 source image.
- **`radius`**: The radius (in pixels) of the identified feature (defaults to 0).
- **`label`**: The specific class for this coordinate.

### Updated Metadata

Post-annotation, the metadata block is expanded:

```json
"metadata": {
  "source": "JSOC_HMI_JPG",
  "captured_at": "2026-03-16",
  "annotator": "github_username",
  "issue_number": 42,
  "timestamp": "2026-03-17T14:30:00Z"
}
```

---

## Directory Structure

- **`data/`**: Contains active tasks available for the frontend.
- **`annotations/`**: Stores task templates that are pending user labels.
- **`data_processing/`**: Temporary workspace used during the nightly pipeline.

Each subdirectory contains files named by task type (e.g., `sunspot.json`, `magnetogram.json`).
