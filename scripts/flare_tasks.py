"""Creates tasks asking which active region produced flares the catalogue left unassigned."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
import requests

try:
    from scripts.science_dataset import CHANNELS, ephemeris, pixel_from_stonyhurst, solar_coordinates
except ModuleNotFoundError:
    from science_dataset import CHANNELS, ephemeris, pixel_from_stonyhurst, solar_coordinates

HEK_URL = "https://www.lmsal.com/hek/her"
HEADERS = {"User-Agent": "SolarHub-Aurora/1.0"}
FLARE_CHANNEL = "aia_131"
FLARE_CLASSES = ("C", "M", "X")
LOOKBACK_DAYS = 7
BEFORE_MINUTES = 20
MATCH_MINUTES = 10
MAX_FRAME_GAP_MINUTES = 15
REGION_RING = 40
REGION_DAYS_BEFORE = 1
REGION_DAYS_AFTER = 2
OTHER_CATALOGUES = ("SSW Latest Events", "Flare Detective - Trigger Module")


def hek_events(event_type: str, start: datetime, end: datetime, fields: str) -> list[dict[str, Any]]:
    events, page = [], 1
    while True:
        params = {
            "cosec": 2, "cmd": "search", "type": "column", "event_type": event_type,
            "event_starttime": start.strftime("%Y-%m-%dT%H:%M:%S"), "event_endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_coordsys": "helioprojective", "x1": -5000, "x2": 5000, "y1": -5000, "y2": 5000,
            "result_limit": 500, "page": page, "return": fields,
        }
        reply = requests.get(HEK_URL, params=params, headers=HEADERS, timeout=90)
        reply.raise_for_status()
        body = reply.json()
        events += body.get("result", [])
        if not body.get("overmax"):
            return events
        page += 1


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _clock(url: str) -> datetime:
    stamp = url.rsplit("/", 1)[-1][:15]
    return datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)


def nearest_url(urls: list[str], moment: datetime) -> str | None:
    best = min(urls, key=lambda url: abs((_clock(url) - moment).total_seconds()), default=None)
    return best if best and abs((_clock(best) - moment).total_seconds()) <= MAX_FRAME_GAP_MINUTES * 60 else None


def full_noaa(number: Any) -> int | None:
    """Some catalogues drop the leading 1 that NOAA numbers gained in June 2002."""
    return (int(number) + 10000 if int(number) < 10000 else int(number)) if number else None


def synodic_rate(latitude: float) -> float:
    """Snodgrass differential rotation in degrees per day, as seen from Earth."""
    s2 = math.sin(math.radians(latitude)) ** 2
    return 14.252 - 1.678 * s2 - 2.401 * s2 * s2 - 0.9856


def regions_at(regions: list[dict[str, Any]], moment: datetime) -> list[dict[str, Any]]:
    """Places each numbered NOAA region where it sits at the flare time."""
    channel = CHANNELS[FLARE_CHANNEL]
    nearest: dict[int, dict[str, Any]] = {}
    for region in regions:
        number, seen = region.get("ar_noaanum"), _time(region["event_starttime"])
        # A region that flares before NOAA numbers it gets its number a day or two later.
        if number and timedelta(days=-REGION_DAYS_BEFORE) <= seen - moment <= timedelta(days=REGION_DAYS_AFTER):
            if number not in nearest or abs(seen - moment) < abs(_time(nearest[number]["event_starttime"]) - moment):
                nearest[number] = region
    candidates = {}
    for number, region in nearest.items():
        seen = _time(region["event_starttime"])
        sun_then = ephemeris(seen)
        # HEK positions are in arcseconds; convert them through image pixels at that time.
        x = channel["center"][0] + region["hpc_x"] / channel["plate_scale"]
        y = channel["center"][1] - region["hpc_y"] / channel["plate_scale"]
        place = solar_coordinates(np.array([x]), np.array([y]), channel, sun_then)
        if not place["on_disk"][0]:
            continue
        latitude = float(place["latitude"][0])
        longitude = float(place["longitude"][0]) + synodic_rate(latitude) * (moment - seen).total_seconds() / 86400
        point = pixel_from_stonyhurst(latitude, longitude, channel, ephemeris(moment))
        if point is not None:
            candidates[int(number)] = {"x": round(point[0]), "y": round(point[1]), "r": REGION_RING, "noaa": int(number)}
    return [candidates[number] for number in sorted(candidates)]


def flare_records(start: datetime, end: datetime, frames_for_day: Callable[[datetime], list[str]]) -> list[dict[str, Any]]:
    flares = hek_events("fl", start, end, "frm_name,fl_goescls,ar_noaanum,hpc_x,hpc_y,event_starttime,event_peaktime,event_endtime,kb_archivid")
    regions = hek_events("ar", start - timedelta(days=REGION_DAYS_BEFORE), end + timedelta(days=REGION_DAYS_AFTER), "frm_name,ar_noaanum,hpc_x,hpc_y,event_starttime,event_endtime")
    regions = [item for item in regions if item.get("frm_name") == "NOAA SWPC Observer"]
    others = [item for item in flares if item.get("frm_name") in OTHER_CATALOGUES]
    records = []
    for flare in flares:
        goes = str(flare.get("fl_goescls") or "")
        if flare.get("frm_name") != "SWPC" or not goes.startswith(FLARE_CLASSES) or flare.get("ar_noaanum"):
            continue
        peak, began = _time(flare["event_peaktime"]), _time(flare["event_starttime"])
        day_frames = frames_for_day(peak)
        after, before = nearest_url(day_frames, peak), nearest_url(day_frames + frames_for_day(began - timedelta(minutes=BEFORE_MINUTES)), began - timedelta(minutes=BEFORE_MINUTES))
        candidates = regions_at(regions, peak)
        if not after or not before or before == after:
            continue
        nearby = [item for item in others if abs((_time(item["event_peaktime"]) - peak).total_seconds()) <= MATCH_MINUTES * 60]
        records.append({
            "id": "flare-" + hashlib.sha256(flare["kb_archivid"].encode()).hexdigest()[:10],
            "url": after,
            "task_type": "flare_source",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "source": "SDO_AIA_BROWSE",
                "captured_at": peak.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "before_url": before,
                "flare": {
                    "catalogue_id": flare["kb_archivid"],
                    "goes_class": goes,
                    "start": flare["event_starttime"] + "Z",
                    "peak": flare["event_peaktime"] + "Z",
                    "end": flare["event_endtime"] + "Z",
                },
                "candidates": candidates,
                # Kept for comparison in the catalogue; SolarHub never shows these to volunteers.
                "other_catalogues": [
                    {"catalogue": item["frm_name"], "noaa": full_noaa(item.get("ar_noaanum")), "hpc_x": round(item["hpc_x"], 1), "hpc_y": round(item["hpc_y"], 1)}
                    for item in nearby
                ],
            },
            "annotations": [],
        })
    return records


def recent_flare_records(today: datetime, frames_for_day: Callable[[datetime], list[str]]) -> list[dict[str, Any]]:
    return flare_records(today - timedelta(days=LOOKBACK_DAYS), today, frames_for_day)
