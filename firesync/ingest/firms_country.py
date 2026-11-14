"""Download NASA FIRMS yearly country archives (standard processing, no key).

URL pattern:
https://firms.modaps.eosdis.nasa.gov/data/country/{dir}/{year}/{dir}_{year}_{Country}.csv
where dir is one of modis | viirs-snpp | viirs-jpss1.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)
BASE = "https://firms.modaps.eosdis.nasa.gov/data/country"
UA = "FireSync-Sahel/0.1 (+research; python-urllib)"


def _years_for(dir_name: str, last_year: int) -> range:
    first = {"modis": 2000, "viirs-snpp": 2012, "viirs-jpss1": 2018}[dir_name]
    return range(first, last_year + 1)


def target_path(dir_name: str, year: int, country: str) -> Path:
    return config.RAW / "firms" / dir_name / str(year) / f"{dir_name}_{year}_{country}.csv"


def download_one(dir_name: str, year: int, country: str, retries: int = 3) -> tuple[str, str]:
    dest = target_path(dir_name, year, country)
    if dest.exists() and dest.stat().st_size > 0:
        return "cached", str(dest)
    url = f"{BASE}/{dir_name}/{year}/{dir_name}_{year}_{country}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return "ok", str(dest)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "missing", url
            err = str(e)
        except Exception as e:  # network hiccup
            err = str(e)
        time.sleep(2 * (attempt + 1))
    return f"error: {err}", url


def download_all(countries: list[str] | None = None, last_year: int | None = None,
                 workers: int = 4, progress=None) -> list[tuple[str, str]]:
    countries = countries or config.COUNTRIES
    last_year = last_year or config.LAST_ARCHIVE_YEAR
    jobs = [(d, y, c) for d in ("modis", "viirs-snpp", "viirs-jpss1")
            for y in _years_for(d, last_year) for c in countries]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(lambda j: download_one(*j), jobs)):
            results.append(res)
            if progress:
                progress(i + 1, len(jobs), res)
    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    def _p(i, n, res):
        print(f"[{i}/{n}] {res[0]} {res[1]}", flush=True)
    out = download_all(progress=_p)
    bad = [r for r in out if r[0].startswith("error")]
    print(f"done: {len(out)} files, {len(bad)} errors")
    sys.exit(1 if bad else 0)
