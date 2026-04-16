"""
merge_annotations_to_hf.py
==========================
Pipeline Stage 3 — Merge Annotations

URL-based synchronization: 
- If URL exists on HF, appends local annotations to the remote record.
- Otherwise, appends as a new row.
Optimized for data integrity and performance by avoiding full remote pulls
unless conflicts (existing URLs) are detected.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_DIR = REPO_ROOT / "annotations"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# Desired column order for consistency
PREFERRED_KEY_ORDER = ["id", "url", "task_type", "created_at", "metadata", "annotations"]

def _normalize_url(url: Any) -> str:
    """Ensure URL is a string and normalized to absolute form."""
    s = str(url).strip()
    if s.startswith("//"):
        return "http:" + s
    # If the URL is already absolute (starts with http), return as is
    return s

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

def _migrate_annotations(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Migrate legacy x,y,r or absolute RLE to compressed RLE."""
    if not isinstance(annotations, list):
        return annotations
        
    for a in annotations:
        if "locations" in a:
            new_locs = []
            for loc in a["locations"]:
                if not isinstance(loc, dict):
                    continue
                
                # Case 1: Already has RLE, check if it needs compression
                if "rle" in loc:
                    rle_val = loc["rle"]
                    parts = rle_val.split()
                    if len(parts) > 2:
                        try:
                            p0, p1, p2 = int(parts[0]), int(parts[1]), int(parts[2])
                            if p2 > p0 + p1: # Absolute RLE detected
                                new_parts = [parts[0], parts[1]]
                                last_end = p0 + p1
                                for i in range(2, len(parts), 2):
                                    start = int(parts[i])
                                    length = parts[i+1]
                                    gap = start - last_end
                                    new_parts.extend([str(gap), length])
                                    last_end = start + int(length)
                                loc["rle"] = " ".join(new_parts)
                        except (ValueError, IndexError):
                            pass
                    new_locs.append(loc)
                
                # Case 2: Legacy x,y,r
                elif all(k in loc for k in ["x", "y"]):
                    label = loc.get("label", "unknown")
                    x, y = float(loc["x"]), float(loc["y"])
                    r = float(loc.get("radius", loc.get("r", 0)))
                    rle = circle_to_rle(x, y, r)
                    new_locs.append({"label": label, "rle": rle})
                
                else:
                    new_locs.append(loc)
            a["locations"] = new_locs
    return annotations

def _safe_value(value: Any) -> Any:
    """Keep scalar values as-is; normalise dict/list into minified JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return value

def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe_value(v) for k, v in record.items()}

def _merge_annotations_list(remote_str: str | None, local_list: list[dict[str, Any]]) -> str:
    """
    Merge local annotation objects into the remote JSON-stringified list.
    Deduplicates based on the JSON string representation of each annotation object.
    """
    def parse_list(s):
        if not s: return []
        try:
            val = json.loads(s)
            return val if isinstance(val, list) else [val]
        except: 
            log.warning("Could not parse JSON string as a list: %s", s)
            return []
    remote_list = parse_list(remote_str)

    def _normalize_annotation(obj: dict[str, Any]) -> dict[str, Any]:
        # Make a shallow copy to avoid mutating input
        ann = dict(obj)
        # Normalize locations to use `region` key (migrate older `rle` if present)
        locs = ann.get("locations")
        if isinstance(locs, str):
            try:
                locs = json.loads(locs)
            except Exception:
                locs = []
        new_locs = []
        if isinstance(locs, list):
            for l in locs:
                if not isinstance(l, dict):
                    continue
                lcopy = dict(l)
                if "rle" in lcopy and "region" not in lcopy:
                    lcopy["region"] = lcopy.pop("rle")
                new_locs.append(lcopy)
        ann["locations"] = new_locs
        return ann

    # Append-only merge: normalize both remote and local lists and concatenate.
    merged_list = []
    for item in remote_list:
        norm = _normalize_annotation(item) if isinstance(item, dict) else item
        merged_list.append(norm)

    for item in local_list:
        norm = _normalize_annotation(item) if isinstance(item, dict) else item
        merged_list.append(norm)

    return json.dumps(merged_list, separators=(",", ":"))

def _push_to_hf(task_type: str, local_records_raw: list[dict[str, Any]], token: str) -> None:
    # Upload per-day files only; no full-merge performed here.

    repo_id = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    # 1. Normalize local records
    local_url_map = {}
    for r in local_records_raw:
        norm_r = _normalise_record(r)
        if "url" in norm_r:
            norm_r["url"] = _normalize_url(norm_r["url"])
            # Pre-migrate local annotations
            if "annotations" in norm_r and isinstance(r.get("annotations"), list):
                norm_r["annotations"] = _safe_value(_migrate_annotations(r["annotations"]))
            local_url_map[norm_r["url"]] = norm_r

    if not local_url_map:
        log.info("No records to process for %s.", task_type)
        return

    # Always write and upload as data/YYYY-MM-DD.yml
    try:
        from datetime import datetime
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        tmp_dir = REPO_ROOT / "tmp_hf_uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        date_key = datetime.utcnow().date().isoformat()
        local_path = tmp_dir / f"{date_key}.yml"
        with open(local_path, "w", encoding="utf-8") as out_f:
            for r in local_url_map.values():
                out_f.write(json.dumps(r, separators=(",", ":")) + "\n")

        repo_path = f"data/{date_key}.yml"
        try:
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=repo_path,
                repo_id=repo_id,
                repo_type="dataset",
                token=token,
                commit_message=f"chore: update daily annotations in {repo_path}"
            )
            log.info("Uploaded %s to %s:%s", local_path, repo_id, repo_path)
        except Exception as e:
            log.warning("Failed to upload %s to %s: %s", local_path, repo_id, e)
        finally:
            try:
                local_path.unlink()
            except Exception:
                pass

        # cleanup tmp dir if empty
        try:
            tmp_dir.rmdir()
        except Exception:
            pass

    except Exception as e:
        log.warning("Daily file upload failed for %s: %s", repo_id, e)




def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)
    
    target_files = list(ANNOTATIONS_DIR.glob("*.jsonl"))

    for task_file in target_files:
        task_type = task_file.stem
        local_records = []
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        local_records.append(json.loads(line))

            # Sync: always upload daily files; full merge happens inside _push_to_hf when it's UTC day 1
            _push_to_hf(task_type, local_records, token)

        except Exception as exc:
            log.warning("Error processing %s: %s", task_file.name, exc)

if __name__ == "__main__":
    main()
