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
  ```json
  {
    "id": "sp-1234",
    "serial_number": 1234,
    "url": "http://jsoc.stanford.edu/data/hmi/images/2026/03/16/000000_Ic_1k.jpg",
    "task_type": "sunspot",
    "ml_label": null,
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
  | `ml_label` | `string` | The classification label assigned by the ML model (defaults to `null`). |
  | `annotations` | `list` | A list of user annotation entries. Each entry contains `locations`, `annotator`, `issue_number`, and `timestamp`. |
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
- **`label`**: The specific classification label for this location.

### Annotation Entry

Each user contribution is stored as an entry in the `annotations` list:

```json
{
  "locations": [
    { "x": 450, "y": 210, "radius": 15, "label": "active_region" },
    { "x": 890, "y": 110, "radius": 10, "label": "quiet_sun" }
  ],
  "annotator": "github_username",
  "issue_number": 42,
  "timestamp": "2026-03-17T14:30:00Z"
}
```

---

## Task Record Schema

Each task (e.g., a sunspot or magnetogram image) is represented as a JSON object within a list.

```json
{
  "id": "sp-1234",
  "serial_number": 1234,
  "url": "http://jsoc.stanford.edu/data/hmi/images/2026/03/16/000000_Ic_1k.jpg",
  "task_type": "sunspot",
  "ml_label": null,
  "annotations": [
    {
      "locations": [
        { "x": 450, "y": 210, "radius": 11, "label": "active_region" }
      ],
      "annotator": "github_username",
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
| `id` | `string` | Unique identifier (e.g., `mg-` prefix for magnetograms). |
| `serial_number` | `integer` | Global incrementing number for the task type. |
| `url` | `string` | Direct link to the solar observation image. |
| `task_type` | `string` | One of `sunspot`, `magnetogram`, `solar_flare`, etc. |
| `ml_label` | `string` | The classification label assigned by the ML model (defaults to `null`). |
| `annotations` | `list` | A list of user annotation entries. Each entry contains `locations`, `annotator`, `issue_number`, and `timestamp`. |
| `metadata` | `object` | Contextual information like capture date and source API. |
