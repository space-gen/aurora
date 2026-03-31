# data/

This directory contains task JSON files shown to users on the SolarHub citizen-science platform.

## File Format

Each task file follows this structure:

```json
{
  "url": "https://solar-data-source/file.jpg",
  "task_type": "sunspot",
  "ml_prediction": null,
  "confidence": null,
  "points": 0,
  "user_comments": []
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | URL pointing to the official solar observation image |
| `task_type` | string | Type of classification task (`sunspot`, `solar_flare`, `magnetogram`, `coronal_hole`) |
| `ml_prediction` | string \| null | ML model prediction (populated after nightly inference) |
| `confidence` | float \| null | Model confidence score (0.0–1.0) |
| `points` | int | User reward points earned for this task |
| `user_comments` | array | List of freeform comments from users |

## Notes

- No real scientific data is stored here — only URLs pointing to official data sources.
- During nightly pipeline execution this directory is renamed to `data_processing/`.
- After pipeline completion it is renamed back to `data/`.
