"""
migrate_annotations_schema.py
=============================
Convert existing annotation files to the new per-annotator `annotations_by_user`
and `annotation_history` schema.

For each annotations/<task>.json file the script will:
 - create a backup annotations/<task>.json.bak.TIMESTAMP
 - for each task record:
     - move `user_label` + `locations` into annotations_by_user[metadata.annotator]
     - move any existing `annotations` list entries into annotations_by_user
     - append corresponding entries into `annotation_history`
 - write the transformed file back (non-destructive: backup retained)

Run locally and inspect changes before pushing to remote.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

TS = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def migrate_file(path: Path) -> None:
    bak = path.with_suffix(path.suffix + f".bak.{TS}")
    shutil.copy(path, bak)
    data = json.loads(path.read_text())
    changed = False

    for rec in data:
        # Ensure structures
        rec.setdefault("annotations_by_user", {})
        rec.setdefault("annotation_history", [])

        annotator = None
        meta = rec.get("metadata") or {}
        annotator = meta.get("annotator")
        issue_number = meta.get("issue_number")
        timestamp = meta.get("timestamp")

        # 1) Migrate top-level user_label + locations -> annotations_by_user
        if annotator and (rec.get("user_label") or rec.get("locations")):
            regions = []
            ul = rec.get("user_label")
            locs = rec.get("locations") or []
            # If locations present, normalize
            for loc in locs:
                # loc may be legacy numeric {x,y,radius,label} or modern {label, rle}
                label = ul
                if isinstance(loc, dict):
                    label = loc.get("label") or ul
                    if "rle" in loc:
                        regions.append({"label": label, "rle": loc.get("rle")})
                    else:
                        regions.append({
                            "label": label,
                            "x": loc.get("x"),
                            "y": loc.get("y"),
                            "radius": loc.get("radius", 0),
                        })
                else:
                    # unexpected type - skip
                    continue
            if regions:
                rec["annotations_by_user"].setdefault(annotator, [])
                rec["annotations_by_user"][annotator].extend(regions)
                rec["annotation_history"].append({"annotator": annotator, "issue_number": issue_number, "timestamp": timestamp, "regions": regions})
                changed = True
            # Remove old top-level fields
            if "user_label" in rec:
                del rec["user_label"]
            if "locations" in rec:
                del rec["locations"]

        # 2) Migrate existing 'annotations' list (older format)
        anns = rec.get("annotations")
        if isinstance(anns, list) and anns:
            for a in anns:
                a_annotator = a.get("annotator") or annotator or "unknown"
                a_regions = []
                for loc in a.get("locations", []):
                    if isinstance(loc, dict) and "rle" in loc:
                        a_regions.append({"label": loc.get("label"), "rle": loc.get("rle")})
                    else:
                        a_regions.append({
                            "label": loc.get("label"),
                            "x": loc.get("x"),
                            "y": loc.get("y"),
                            "radius": loc.get("radius", 0),
                        })
                if a_regions:
                    rec["annotations_by_user"].setdefault(a_annotator, [])
                    rec["annotations_by_user"][a_annotator].extend(a_regions)
                    rec["annotation_history"].append({"annotator": a_annotator, "issue_number": a.get("issue_number"), "timestamp": a.get("timestamp"), "regions": a_regions})
                    changed = True
            # remove old list
            del rec["annotations"]

    if changed:
        path.write_text(json.dumps(data, indent=2))
        print(f"Migrated {path} (backup: {bak})")
    else:
        print(f"No changes for {path}")


def main() -> None:
    for p in ANNOTATIONS_DIR.glob("*.json"):
        migrate_file(p)


if __name__ == "__main__":
    main()
