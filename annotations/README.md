# annotations/

This directory holds annotation files produced from user-submitted GitHub issues.

## Lifecycle

1. During each nightly pipeline run, annotation templates are copied from `data_processing/`
   into this directory (pipeline stage 4 — `04_sync_annotations.yml`).

2. Annotations remain here until they are **successfully merged** into the HuggingFace dataset
   (`03_merge_annotations.yml`).

3. After a successful merge the annotation content is cleared, but the files themselves remain
   as empty placeholders ready for the next cycle.

## File Format

Annotation files mirror the task JSON format and add a `user_label` field:

```json
{
  "url": "https://solar-data-source/file.jpg",
  "task_type": "sunspot",
  "user_label": "active_region",
  "metadata": {
    "annotator": "github_username",
    "timestamp": "2026-01-01T00:00:00Z"
  }
}
```

## Notes

- Annotation files are **never** pushed directly to HuggingFace without passing through the
  `merge_annotations_to_hf.py` script.
- `data_processing/` and HuggingFace datasets must never mix automatically.
