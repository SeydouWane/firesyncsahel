"""Facts and figures for the FireSync Sahel pitch deck (computed from the project's own data).

Run with the FireSync server up (python -m firesync serve):
    python presentation/build_data.py
Writes presentation/assets/deck_data.json and the chart images.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from firesync import config  # noqa: E402
from firesync.grid import cell_center  # noqa: E402
from firesync.ingest import boundaries  # noqa: E402

API = "http://127.0.0.1:8000"
OUT = ROOT / "presentation" / "assets"
OUT.mkdir(parents=True, exist_ok=True)
SAHEL_RAW = ROOT / "presentation" / "sahel_firms"  # kept apart from data/raw: not part of the pipeline


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Requested-With": "firesync"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def get(path):
    return json.load(urllib.request.urlopen(API + path, timeout=600))


# ------------------------------------------------------------------ departments (Senegal)
def departments():
    gj = boundaries.load(2)
    rows = []
    for f in gj["features"]:
        p = f["properties"]
        if p["iso3"] != "SEN":
            continue
        cal = post("/api/zone/calendar", {"geometry": f["geometry"], "name": p["name"], "lang": "fr"})["calendar"]
        yrs = [y for y in cal["years"] if y["complete"] and y["total"] is not None]
        tot = np.array([y["total"] for y in yrs])
        rows.append({"id": p["id"], "name": p["name"], "region": p.get("parent"), "area_km2": cal["area_km2"],
                     "mean_total": float(tot.mean()), "max_total": float(tot.max()),
                     "max_label": yrs[int(tot.argmax())]["label"], "n_years": len(yrs),
                     "density": float(tot.mean() / cal["area_km2"] * 1000),
                     "onset": cal["summary"].get("onset"), "peak": cal["summary"].get("peak"),
                     "end": cal["summary"].get("end"), "labels": cal["week_labels"],
                     "trend": (cal.get("trends") or {}).get("total")})
        print(f"  {p['name']:<22} {rows[-1]['mean_total']:9.0f} det/yr  {rows[-1]['density']:6.1f} /1000 km²", flush=True)
    return rows


def burned_by_department(deps):
    """MCD64A1 burned km² per department and year (H3 res-5 cells assigned by centroid)."""
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    gj = boundaries.load(2)
    polys = [(f["properties"]["id"], prep(shape(f["geometry"]))) for f in gj["features"] if f["properties"]["iso3"] == "SEN"]
    ba = pl.read_parquet(config.PROCESSED / "burned_week.parquet")
    cells = ba["h3_5"].unique().to_list()
    owner = {}
    for c in cells:
        lat, lon = cell_center(int(c))
        pt = Point(lon, lat)
        for did, poly in polys:
            if poly.contains(pt):
                owner[c] = did
                break
    m = pl.DataFrame({"h3_5": list(owner), "dep": list(owner.values())})
    by = (ba.join(m, on="h3_5").filter(pl.col("year") <= 2024)
          .group_by(["dep", "year"]).agg(pl.col("ba_km2").sum()))
    nat = by.group_by("year").agg(pl.col("ba_km2").sum()).sort("year")
    mean_dep = by.group_by("dep").agg(pl.col("ba_km2").mean().alias("ba_mean"))
    out = {r["dep"]: r["ba_mean"] for r in mean_dep.to_dicts()}
    for d in deps:
        d["ba_mean_km2"] = out.get(d["id"])
        d["ba_frac"] = (out.get(d["id"]) or 0) / d["area_km2"]
    return {"years": nat["year"].to_list(), "km2": nat["ba_km2"].to_list()}


# ------------------------------------------------------------------ Sahel (NASA FIRMS MODIS 2024)
SAHEL = {"Senegal": ("Sénégal", 196722), "The_Gambia": ("Gambie", 11295), "Mauritania": ("Mauritanie", 1030700),
         "Mali": ("Mali", 1240192), "Burkina_Faso": ("Burkina Faso", 274200), "Niger": ("Niger", 1267000),
         "Chad": ("Tchad", 1284000), "Guinea": ("Guinée", 245857)}


def sahel(year=2024):
    SAHEL_RAW.mkdir(parents=True, exist_ok=True)
    out = []
    for c, (fr, area) in SAHEL.items():
        dest = SAHEL_RAW / f"modis_{year}_{c}.csv"
        if not dest.exists():
            url = f"https://firms.modaps.eosdis.nasa.gov/data/country/modis/{year}/modis_{year}_{c}.csv"
            req = urllib.request.Request(url, headers={"User-Agent": "FireSync-Sahel/0.1 (+research)"})
            dest.write_bytes(urllib.request.urlopen(req, timeout=300).read())
        n = 0
        months = [0] * 12
        with open(dest, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("type", "0") not in ("0", ""):
                    continue  # presumed vegetation fires only (same rule as FireSync)
                n += 1
                months[int(r["acq_date"][5:7]) - 1] += 1
        out.append({"country": c, "name": fr, "area_km2": area, "n": n, "per_1000km2": n / area * 1000, "months": months})
        print(f"  {fr:<14} {n:8d} MODIS detections in {year}", flush=True)
    return out


def main():
    print("departments…")
    deps = departments()
    print("burned area…")
    nat_ba = burned_by_department(deps)
    print("region series…")
    reg = get("/api/region/summary?lang=fr")
    print("forecast…")
    fc = get("/api/forecast?lang=fr")
    print("Sahel FIRMS 2024…")
    sah = sahel(2024)
    v = get("/api/validation")
    data = {"departments": deps, "senegal_ba": nat_ba, "region": reg, "sahel": sah,
            "forecast": {"issue": fc["issue"], "region": fc["region"], "validation": fc["validation"],
                         "units": [{k: u[k] for k in ("id", "name", "level", "iso3", "parent", "next2", "next4")}
                                   for u in fc["units"]]},
            "validation": v}
    (OUT / "deck_data.json").write_text(json.dumps(data, ensure_ascii=False, default=float), encoding="utf-8")
    print("ok", OUT / "deck_data.json")


if __name__ == "__main__":
    main()
