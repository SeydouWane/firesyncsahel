"""Hexagonal grid helpers (Uber H3, integer cell ids)."""
from __future__ import annotations

from functools import lru_cache

import h3
import h3.api.basic_int as h3i
import numpy as np
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from .config import GRID


def latlng_to_cells(lat: np.ndarray, lon: np.ndarray, res: int) -> np.ndarray:
    f = h3i.latlng_to_cell
    return np.fromiter((f(a, b, res) for a, b in zip(lat.tolist(), lon.tolist())),
                       dtype=np.int64, count=len(lat))


def parents(cells: np.ndarray, res: int) -> np.ndarray:
    """Parent ids at `res`, computed on unique values only (fast)."""
    uniq, inv = np.unique(cells, return_inverse=True)
    par = np.fromiter((h3i.cell_to_parent(int(c), res) for c in uniq), dtype=np.int64,
                      count=len(uniq))
    return par[inv]


@lru_cache(maxsize=200_000)
def cell_center(cell: int) -> tuple[float, float]:
    return h3i.cell_to_latlng(int(cell))


def cell_boundary_lonlat(cell: int) -> list[list[float]]:
    ring = [[lng, lat] for lat, lng in h3i.cell_to_boundary(int(cell))]
    ring.append(ring[0])
    return ring


def cell_area_km2(cell: int) -> float:
    return h3i.cell_area(int(cell), unit="km^2")


def geometry_to_cells(geom: BaseGeometry | dict, res: int = GRID.fine_res) -> np.ndarray:
    """H3 cells whose centre lies in the geometry (Polygon or MultiPolygon).

    Very small polygons that contain no cell centre fall back to the cells of
    the polygon's representative point and vertices, so a query never returns
    an empty zone.
    """
    g = shape(geom) if isinstance(geom, dict) else geom
    if not g.is_valid:
        g = g.buffer(0)
    geo = mapping(g)
    shp = h3.geo_to_h3shape(geo)
    cells = [h3.str_to_int(c) for c in h3.h3shape_to_cells(shp, res)]
    if not cells:
        pts = [g.representative_point().coords[0]]
        if hasattr(g, "exterior"):
            pts += list(g.exterior.coords)
        cells = list({h3i.latlng_to_cell(y, x, res) for x, y in pts})
    return np.array(sorted(set(cells)), dtype=np.int64)


def cells_to_geojson(cells, props: dict | None = None) -> dict:
    feats = []
    for c in cells:
        p = {"h3": str(int(c))}
        if props and int(c) in props:
            p.update(props[int(c)])
        feats.append({"type": "Feature", "properties": p,
                      "geometry": {"type": "Polygon", "coordinates": [cell_boundary_lonlat(c)]}})
    return {"type": "FeatureCollection", "features": feats}
