"""
pull_new_urls.py
================
Stage 2 — Daily Solar Data Crawler

Fetches sunspot and magnetogram JPG URLs (HMI) + NASA SDO 1024px AIA browse JPGs.
Parallelized fetch for faster performance.
"""

import re
import json
import logging
import datetime
import argparse
import sys
from functools import lru_cache
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Config
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"

# 4500 is omitted: its browse frames are overexposed and show no usable surface detail.
AIA_WAVELENGTHS = ["94", "131", "171", "193", "211", "304", "335", "1600", "1700"]
# Only tasks that produce data researchers lack: coronal holes, filaments and prominences.
RESEARCH_TASKS = ["aia_193", "aia_211", "aia_304"]
NO_BLEND_TASKS = set(RESEARCH_TASKS)

SOURCE_MAP = {
    "sunspot": {
        "path": "https://jsoc1.stanford.edu/data/hmi/images/{Y}/{M}/{D}/",
        "filter": "_Ic_flat_1k.jpg",
        "prefix": "sp",
        "source_type": "JSOC_HMI_JPG"
    },
    "magnetogram": {
        "path": "https://jsoc1.stanford.edu/data/hmi/images/{Y}/{M}/{D}/",
        "filter": "_M_1k.jpg",
        "prefix": "mg",
        "source_type": "JSOC_HMI_JPG"
    },
}

# Add AIA entries dynamically
for wavelength in AIA_WAVELENGTHS:
    SOURCE_MAP[f"aia_{wavelength}"] = {
        "path": "https://sdo.gsfc.nasa.gov/assets/img/browse/{Y}/{M}/{D}/",
        "filter": f"_1024_{int(wavelength):04d}.jpg",
        "prefix": f"aia{wavelength}",
        "wavelength": wavelength,
        "source_type": "SDO_AIA_BROWSE"
    }

LINK_REGEX = re.compile(r'href="([^"]+)"')

MAX_WORKERS = 10
CANDIDATE_STRIDE = 8
MAX_BLEND_GAP_SECONDS = 1800
REQUEST_HEADERS = {"User-Agent": "SolarHub-Aurora/1.0"}


def _canonical_url(url):
    return re.sub(r"^https?://jsoc1?\.stanford\.edu/", "https://jsoc1.stanford.edu/", url.strip())


def existing_ids_by_url(path):
    """Keeps record IDs stable when the same day is crawled again."""
    if not path.exists():
        return {}
    ids = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                ids[_canonical_url(item.get("url", ""))] = item.get("id")
    return ids


def _finder():
    try:
        from scripts import find_candidates as finder
    except ModuleNotFoundError:
        import find_candidates as finder
    return finder


def _download(url):
    response = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return response.content


def _clock_seconds(url):
    clock = re.search(r"_(\d{2})(\d{2})(\d{2})_1024_", url)
    return int(clock[1]) * 3600 + int(clock[2]) * 60 + int(clock[3])


def nearest_frame(urls, url):
    """Finds the closest frame in another channel, so a blend shows one moment."""
    target = _clock_seconds(url)
    best = min(urls, key=lambda item: abs(_clock_seconds(item) - target), default=None)
    return best if best and abs(_clock_seconds(best) - target) <= MAX_BLEND_GAP_SECONDS else None


@lru_cache(maxsize=8)
def _channel_urls(wavelength, date_obj):
    return tuple(sorted(_fetch_single_day(f"aia_{wavelength}", date_obj)))


@lru_cache(maxsize=16)
def _context_from(urls):
    finder = _finder()
    frames = {wavelength: finder.gray_from_jpeg(_download(url)) for wavelength, url in urls}
    return finder.blend_context(frames)


def _blend_context(url, date_obj):
    finder = _finder()
    urls = tuple((wavelength, nearest_frame(_channel_urls(wavelength, date_obj), url)) for wavelength in finder.BLEND_WAVELENGTHS)
    return None if any(item is None for _, item in urls) else _context_from(urls)


def add_candidates(task_type, records, date_obj):
    """Adds features to check on every eighth frame, which is what contributors see first."""
    finder = _finder()

    def enrich(record):
        try:
            content = _download(record["url"])
            try:
                context = None if task_type in NO_BLEND_TASKS else _blend_context(record["url"], date_obj)
            except Exception as e:
                log.warning(f"Using one channel for {record['url']}: {e}")
                context = None
            record["metadata"]["candidates"] = finder.candidates_from_jpeg(content, task_type, context)
        except Exception as e:
            log.warning(f"Could not find candidates in {record['url']}: {e}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        list(executor.map(enrich, records[::CANDIDATE_STRIDE]))


def _get_last_id_numeric(task_type):
    max_id = 0
    prefix = SOURCE_MAP[task_type]["prefix"]

    for p in REPO_ROOT.glob("**/*.jsonl"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    item = json.loads(line)

                    if item.get("task_type") == task_type:
                        id_str = item.get("id", "")
                        if id_str.startswith(f"{prefix}-"):
                            try:
                                num = int(id_str.split("-")[1])
                                max_id = max(max_id, num)
                            except Exception:
                                pass
        except Exception:
            pass

    return max_id


def _fetch_single_day(task_type, date_obj):
    y = date_obj.strftime("%Y")
    m = date_obj.strftime("%m")
    d = date_obj.strftime("%d")

    cfg = SOURCE_MAP[task_type]
    
    # For AIA, include wavelength in the URL
    if task_type.startswith("aia_"):
        wavelength = cfg.get("wavelength")
        base_url = cfg["path"].format(Y=y, M=m, D=d, wavelength=wavelength)
    else:
        base_url = cfg["path"].format(Y=y, M=m, D=d)

    results = []

    try:
        response = requests.get(base_url, timeout=30, headers=REQUEST_HEADERS)

        if response.status_code == 200:
            matches = LINK_REGEX.findall(response.text)

            for match in matches:
                if match.endswith(cfg["filter"]):
                    results.append(base_url + match)
        else:
            log.warning(f"Failed {base_url} ({response.status_code})")

    except Exception as e:
        log.warning(f"Error {base_url}: {e}")

    return results


def _fetch_day_urls_parallel(task_type, date_obj):
    dates = [date_obj]
    all_results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_single_day, task_type, d): d
            for d in dates
        }

        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as e:
                log.warning(f"Thread failed: {e}")

    return all_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=1)
    parser.add_argument("--include-aia", action="store_true", help="Include AIA data in the pull")
    args = parser.parse_args()

    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    # Only flares are published now: the site works out 193, 211 and 304 pictures from NASA's archive itself.
    for path in DATA_PROCESSING_DIR.glob("*.jsonl"):
        if path.stem != "flare_source":
            path.unlink()

    if args.include_aia:
        try:
            from scripts.flare_tasks import recent_flare_records
        except ModuleNotFoundError:
            from flare_tasks import recent_flare_records
        try:
            today = datetime.datetime.now(datetime.timezone.utc)
            flares = recent_flare_records(today, lambda wavelength, moment: list(_channel_urls(wavelength, moment.date())), _download)
            with open(DATA_PROCESSING_DIR / "flare_source.jsonl", "w", encoding="utf-8") as f:
                for record in flares:
                    f.write(json.dumps(record, separators=(",", ":")) + "\n")
            log.info(f"{len(flares)} flare tasks saved")
        except Exception as e:
            # Flare tasks depend on the HEK service; image tasks should still publish without them.
            log.warning(f"Could not build flare tasks: {e}")



if __name__ == "__main__":
    main()
