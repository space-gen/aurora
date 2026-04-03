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
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

TS = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def circle_to_rle(cx: float, cy: float, r: float, width: int = 1024) -> str:
    """
    Convert a circle (cx, cy, r) to a run-length encoded (RLE) string.
    RLE format: start1 length1 start2 length2 ... (1D pixel indices)
    """
    rle_parts = []
    # Iterate through rows that the circle covers
    for y in range(int(cy - r), int(cy + r) + 1):
        if y < 0 or y >= 1024: # Assuming 1024 height
            continue
        dy = y - cy
        dx = math.sqrt(max(0, r*r - dy*dy))
        x1 = max(0, int(cx - dx))
        x2 = min(width - 1, int(cx + dx))
        
        if x1 <= x2:
            start_idx = y * width + x1
            length = x2 - x1 + 1
            rle_parts.extend([str(start_idx), str(length)])
    
    return " ".join(rle_parts)

def migrate_file(path: Path) -> None:
    bak = path.with_suffix(path.suffix + f".bak.{TS}")
    shutil.copy(path, bak)
    
    # Read as JSONL if it's .jsonl, otherwise .json
    is_jsonl = path.suffix == ".jsonl"
    
    tasks = []
    changed = False

    if is_jsonl:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                tasks.append(json.loads(line))
    else:
        tasks = json.loads(path.read_text())

    for rec in tasks:
        # 1) Migrate 'annotations' list (older format or current format)
        anns = rec.get("annotations")
        if isinstance(anns, list) and anns:
            for a in anns:
                if "locations" in a:
                    new_locs = []
                    for loc in a["locations"]:
                        if isinstance(loc, dict):
                            if "rle" in loc:
                                new_locs.append(loc)
                            elif all(k in loc for k in ["x", "y"]):
                                # Convert x,y,radius to RLE
                                label = loc.get("label", "unknown")
                                x = float(loc["x"])
                                y = float(loc["y"])
                                r = float(loc.get("radius", loc.get("r", 0)))
                                rle = circle_to_rle(x, y, r)
                                new_locs.append({"label": label, "rle": rle})
                                changed = True
                        else:
                            # Handle non-dict or malformed
                            continue
                    a["locations"] = new_locs

    if changed:
        if is_jsonl:
            with open(path, "w", encoding="utf-8") as f:
                for t in tasks:
                    f.write(json.dumps(t, separators=(",", ":")) + "\n")
        else:
            path.write_text(json.dumps(tasks, indent=2))
        print(f"Migrated {path} (backup: {bak})")
    else:
        # Cleanup backup if no changes
        bak.unlink()
        print(f"No changes for {path}")


def main() -> None:
    for p in ANNOTATIONS_DIR.glob("*.json*"):
        if p.suffix in [".json", ".jsonl"]:
            migrate_file(p)


if __name__ == "__main__":
    main()
