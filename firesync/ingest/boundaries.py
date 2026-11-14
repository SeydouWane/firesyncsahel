"""Administrative units from geoBoundaries (gbOpen, CC BY 3.0 IGO / ODbL).

Writes data/processed/admin_{level}.geojson with harmonised properties:
id, name, level, iso3, parent (ADM1 name for ADM2 units).
"""
from __future__ import annotations

import json
import logging

import requests
from shapely.geometry import mapping, shape

from .. import config

log = logging.getLogger(__name__)
API = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{level}/"


def _fetch(iso: str, level: str) -> dict | None:
    r = requests.get(API.format(iso=iso, level=level), timeout=60)
    if r.status_code != 200:
        return None
    meta = r.json()
    url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
    g = requests.get(url, timeout=120)
    g.raise_for_status()
    gj = g.json()
    gj["_meta"] = {"source": meta.get("boundarySource"), "license": meta.get("boundaryLicense"),
                   "year": meta.get("boundaryYearRepresented")}
    return gj


def build() -> dict:
    out = {}
    adm1_geoms = {}
    for level in ("ADM1", "ADM2"):
        feats, sources = [], []
        for iso in config.ADMIN_ISO3:
            gj = _fetch(iso, level)
            if gj is None:
                continue
            sources.append({"iso3": iso, **gj["_meta"]})
            for i, f in enumerate(gj["features"]):
                p = f.get("properties", {})
                name = p.get("shapeName") or p.get("name") or f"{iso}-{level}-{i}"
                geom = shape(f["geometry"]).buffer(0).simplify(0.003, preserve_topology=True)
                fid = f"{iso}-{level}-{p.get('shapeID', i)}"
                props = {"id": fid, "name": name, "level": int(level[-1]), "iso3": iso}
                if level == "ADM1":
                    adm1_geoms[fid] = (name, geom)
                else:
                    c = geom.representative_point()
                    parent = next((n for n, g in adm1_geoms.values() if g.contains(c)), None)
                    props["parent"] = parent
                feats.append({"type": "Feature", "properties": props,
                              "geometry": mapping(geom)})
        fc = {"type": "FeatureCollection", "features": feats, "sources": sources}
        path = config.PROCESSED / f"admin_{level[-1]}.geojson"
        path.write_text(json.dumps(fc))
        out[level] = len(feats)
        log.info("%s: %d units", level, len(feats))
    return out


def load(level: int) -> dict | None:
    p = config.PROCESSED / f"admin_{level}.geojson"
    return json.loads(p.read_text()) if p.exists() else None
