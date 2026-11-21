# annotations/

This directory holds annotation files produced from user-submitted GitHub issues.

## Lifecycle

1. During each nightly pipeline run, annotation templates are copied from `data_processing/`
   into this directory (pipeline stage 4 — `04_sync_annotations.yml`).

2. Annotations remain here until they are **successfully merged** into the HuggingFace dataset
   (`03_merge_annotations.yml`).

3. After a successful merge the annotation content is cleared, but the files themselves remain
   as empty placeholders ready for the next cycle.

## File Format (NEW)

Annotation files now follow the per-annotator region format. Each task record keeps an
`annotations_by_user` map of annotator -> list of region objects, and an `annotation_history`
list for chronological records.

Example task record:

```json
{
  "id": "sp-1",
  "url": "https://.../file.jpg",
  "task_type": "sunspot",
  "annotations_by_user": {
    "alice": [ { "label":"sunspot", "x":450, "y":320, "radius":15 } ],
    "bob":   [ { "label":"sunspot", "x":452, "y":318, "radius":14 } ]
  },
  "annotation_history": [
    { "annotator":"alice", "issue_number": 12, "timestamp":"2026-03-18T00:00:00Z", "regions":[...] }
  ],
  "metadata": { "source": "JSOC_HMI_JPG", "captured_at": "2026-03-17" }
}
```

Notes:
- The old top-level `user_label` and `locations` fields are migrated into the new
  `annotations_by_user` and `annotation_history` fields by the migration script
  `scripts/migrate_annotations_schema.py` (non-destructive backup created).
- `image_url` remains a required field in the issue form; annotations are now submitted in the `your_label` field using `label,rle` format (multiple annotations separated by `;`). RLE should be a run-length encoding string describing the annotated region's mask.
- Annotation files are **never** pushed directly to HuggingFace without passing through the
  `scripts/merge_annotations_to_hf.py` script which performs schema reconciliation when
  needed.
