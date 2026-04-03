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
import logging
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

TS = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def circle_to_rle(cx: float, cy: float, r: float, width: int = 1024) -> str:
    """
    Convert a circle (cx, cy, r) to a compressed RLE string.
    Format: start1 length1 gap1 length2 gap2 length3 ...
    gap is the distance from the end of the previous run to the start of the current one.
    """
    runs = []
    for y in range(int(cy - r), int(cy + r) + 1):
        if y < 0 or y >= 1024:
            continue
        dy = y - cy
        dx = math.sqrt(max(0, r*r - dy*dy))
        x1 = max(0, int(cx - dx))
        x2 = min(width - 1, int(cx + dx))
        if x1 <= x2:
            runs.append((y * width + x1, x2 - x1 + 1))
    
    if not runs:
        return ""
        
    rle_parts = [str(runs[0][0]), str(runs[0][1])]
    last_end = runs[0][0] + runs[0][1]
    
    for i in range(1, len(runs)):
        start, length = runs[i]
        gap = start - last_end
        rle_parts.extend([str(gap), str(length)])
        last_end = start + length
        
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
                                # Check if it's absolute or compressed
                                rle_val = loc["rle"]
                                parts = rle_val.split()
                                if len(parts) > 2:
                                    # Very naive heuristic: if second start index is very large, it's likely absolute
                                    # In compressed format, the 3rd element is a 'gap' (usually small)
                                    # In absolute format, the 3rd element is a 'start index' (increasing)
                                    try:
                                        p0 = int(parts[0])
                                        p1 = int(parts[1])
                                        p2 = int(parts[2])
                                        if p2 > p0 + p1: # Third element is greater than end of first run -> absolute
                                            # Convert absolute to compressed
                                            new_parts = [parts[0], parts[1]]
                                            last_end = p0 + p1
                                            for i in range(2, len(parts), 2):
                                                start = int(parts[i])
                                                length = parts[i+1]
                                                gap = start - last_end
                                                new_parts.extend([str(gap), length])
                                                last_end = start + int(length)
                                            loc["rle"] = " ".join(new_parts)
                                            changed = True
                                            log.info(f"Compressed absolute RLE for {rec.get('id')}")
                                    except (ValueError, IndexError):
                                        pass
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
