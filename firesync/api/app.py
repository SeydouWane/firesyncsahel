"""FireSync Sahel web API + static front-end.

Spaces
  public  /api/meta, /api/zone/*, /api/map/*, /api/validation, /api/access-request
  pro     /api/pro/*      (role pro or admin, cookie session)
  admin   /api/admin/*    (role admin)
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
import polars as pl
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from shapely.geometry import mapping, shape

from .. import __version__, config, indicators
from ..grid import cells_to_geojson
from ..harmonize import validate as validation
from ..ingest import boundaries, landcover
from ..report import bulletin
from ..series import Store, calendar, sensors_series, weekly_csv, zone_data
from . import auth, db, jobs

@asynccontextmanager
async def _lifespan(_app):
    """Pre-compute the region series and the AI forecast overview in the background,
    so the first visitor of the home page does not wait for them (not on serverless
    hosting, where background work is frozen between requests and the CDN caches)."""
    if config.SERVERLESS:
        yield
        return

    def run():
        for f in (lambda: region_summary("fr"), lambda: forecast_overview("fr"),
                  lambda: forecast_overview("en"), lambda: region_summary("en")):
            try:
                f()
            except Exception:  # data not built yet: pages show their own message
                pass
    threading.Thread(target=run, name="warm-caches", daemon=True).start()
    yield


app = FastAPI(title="FireSync Sahel", version=__version__, docs_url="/api/docs",
              openapi_url="/api/openapi.json", lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


# Public, data-only GET endpoints identical for every visitor: a CDN (Vercel) may keep
# them; its cache is emptied at each deployment, i.e. each data refresh.
_CDN_CACHEABLE = ("/api/forecast", "/api/region/summary", "/api/season/overview", "/api/map/hex",
                  "/api/validation", "/api/admin-units", "/api/reference-zones")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    path = request.url.path
    if request.method == "GET" and resp.status_code == 200 and "cache-control" not in resp.headers:
        if path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=600, s-maxage=86400"
        elif path.startswith(_CDN_CACHEABLE):
            resp.headers["Cache-Control"] = "public, max-age=300, s-maxage=86400, stale-while-revalidate=3600"
    return resp


# ---------------------------------------------------------------- models
class ZoneQuery(BaseModel):
    geometry: dict
    name: str = "Zone"
    start_week: int | str = "auto"
    mode: str = Field("harmonized", pattern="^(harmonized|naive)$")
    lang: str = Field("fr", pattern="^(fr|en)$")


class Login(BaseModel):
    email: str
    password: str


class AccessRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=160)
    org: str = Field("", max_length=160)
    profile: str = Field("", max_length=80)
    message: str = Field("", max_length=2000)


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geometry: dict
    kind: str = "drawn"
    category: str = ""
    alert_pct: float | None = 90
    notes: str = ""


class UserIn(BaseModel):
    email: str
    name: str = ""
    org: str = ""
    role: str = Field("pro", pattern="^(admin|pro)$")
    password: str | None = None


class UserPatch(BaseModel):
    role: str | None = Field(None, pattern="^(admin|pro)$")
    active: bool | None = None
    name: str | None = None
    org: str | None = None


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=8)


class RefZoneIn(BaseModel):
    name: str
    category: str = "foret_classee"
    geojson: dict


# ---------------------------------------------------------------- helpers
def _store() -> Store:
    try:
        return Store.get()
    except FileNotFoundError as e:
        raise HTTPException(503, f"serving tables missing — run `python -m firesync build` ({e.filename})")


def _validate_geom(g: dict) -> dict:
    try:
        if g.get("type") == "Feature":
            g = g["geometry"]
        if g.get("type") == "FeatureCollection":
            from shapely.ops import unary_union
            g = mapping(unary_union([shape(f["geometry"]) for f in g["features"]]))
        geom = shape(g)
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("polygon expected")
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.area > 400:  # ~ 4.9 M km² at the equator
            raise ValueError("zone too large")
        return mapping(geom)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"invalid geometry: {e}")


_cache: OrderedDict[str, dict] = OrderedDict()


def _zone_result(qz: ZoneQuery) -> tuple[dict, object]:
    geom = _validate_geom(qz.geometry)
    key = hashlib.sha1(json.dumps([geom, qz.start_week, qz.mode, qz.lang], sort_keys=True,
                                  default=str).encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    _store()
    zd = zone_data(geom, qz.mode)
    cal = calendar(zd, qz.start_week, qz.lang)
    res = {"calendar": cal, "sensors": sensors_series(zd), "zd": zd}
    _cache[key] = res
    if len(_cache) > 64:
        _cache.popitem(last=False)
    return res


def _validation_headline() -> dict | None:
    rep = validation.load_report()
    if not rep:
        return None
    ta = rep["variants"].get("TA", {})
    out = {}
    for m in ("naive", "single_ratio", "stratified_eb", "gbm"):
        if m in ta:
            l = ta[m]["loyo"]
            out[m] = {"zone_week_nmae": l["zone_week"]["nmae_pct"], "region_year_bias": l["region_year"]["bias_pct"],
                      "zone_week_r": l["zone_week"]["r_log"], "coverage": l["zone_week"].get("coverage90"),
                      "onset_err": ta[m]["season_loyo"]["zone"]["onset"]}
    return out


_cov_cache: dict = {}


def _coverage(st: Store) -> list:
    key = st.meta.get("data_version") or st.meta.get("generated")
    if key not in _cov_cache:
        _cov_cache.clear()
        _cov_cache[key] = st.query("SELECT sensor, min(date)::VARCHAR, max(date)::VARCHAR, count(*) FROM det "
                                   "GROUP BY sensor ORDER BY sensor")
    return _cov_cache[key]


# ---------------------------------------------------------------- public
@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/meta")
def meta(request: Request):
    st = _store()
    m = st.meta
    det_cov = _coverage(st)
    u = auth.current_user(request)
    return {
        "app": "FireSync Sahel", "version": __version__,
        "countries": config.COUNTRIES, "last_date": st.last_date,
        "start_week": m["start_week"], "reference": m["reference"],
        "sensors": [{"sensor": s, "first": a, "last": b, "n": n} for s, a, b, n in det_cov],
        "sources": m["sources"], "land_cover": landcover.meta(),
        "train_fire_years": m["train_fire_years"], "members": m["members"],
        "step_test": {k: v for k, v in (m.get("step_test") or {}).items() if k != "annual"},
        "validation": _validation_headline(),
        "nrt_configured": bool(config.FIRMS_MAP_KEY or db.get_setting("firms_map_key")),
        "snpp_end": config.SENSORS["VIIRS_SNPP"].last,
        "ack": config.FIRMS_ACK,
        "partners": _partners(),
        "user": auth.public_user(u) if u else None,
        "public_bulletins": db.get_setting("public_bulletins", True),
        "serverless": config.SERVERLESS,
    }


@app.get("/api/admin-units")
def admin_units(level: int = 2):
    if level not in (1, 2):
        raise HTTPException(400, "level 1 or 2")
    gj = boundaries.load(level)
    if gj is None:
        raise HTTPException(404, "run `python -m firesync boundaries`")
    return JSONResponse(gj, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/reference-zones")
def reference_zones():
    rows = db.q("SELECT id,name,category,geometry FROM zones WHERE kind='reference' AND public=1 ORDER BY name")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": r["id"], "name": r["name"], "category": r["category"]},
         "geometry": json.loads(r["geometry"])} for r in rows]}


@app.post("/api/zone/calendar")
def zone_calendar(qz: ZoneQuery):
    t0 = time.time()
    res = _zone_result(qz)
    return {"name": qz.name, "calendar": res["calendar"], "sensors": res["sensors"],
            "elapsed_ms": int(1000 * (time.time() - t0))}


@app.post("/api/zone/bulletin")
def zone_bulletin(qz: ZoneQuery, request: Request):
    if not db.get_setting("public_bulletins", True) and not auth.current_user(request):
        raise HTTPException(401, "bulletins are reserved to professional accounts")
    res = _zone_result(qz)
    v = _validation_headline() or {}
    g = v.get("gbm")
    vtxt = None
    if g:
        vtxt = (f"erreur absolue normalisée zone-semaine {g['zone_week_nmae']:.0f} % ; biais annuel régional "
                f"{g['region_year_bias']:+.1f} % ; couverture de l'intervalle 90 % : {100 * (g['coverage'] or 0):.0f} %"
                if qz.lang == "fr" else
                f"zone-week normalised absolute error {g['zone_week_nmae']:.0f}%; regional annual bias "
                f"{g['region_year_bias']:+.1f}%; 90% interval coverage {100 * (g['coverage'] or 0):.0f}%")
    fcz = None
    try:
        fc = _forecaster()
        fcz = fc.zone(fc.weights(_validate_geom(qz.geometry)), qz.lang, qz.name)
    except HTTPException:
        pass
    pdf = bulletin.build(qz.name, res["calendar"], qz.lang, vtxt, _store().last_date, fcz, _partners())
    fname = "".join(ch for ch in qz.name if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_") or "zone"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="FireSync_{fname}_{qz.lang}.pdf"'})


_agg_cache: dict = {}


def _region_geom() -> dict:
    from shapely.ops import unary_union
    gj = boundaries.load(1)
    if not gj:
        raise HTTPException(404, "boundaries missing")
    return mapping(unary_union([shape(f["geometry"]) for f in gj["features"]]).simplify(0.01))


@app.get("/api/region/summary")
def region_summary(lang: str = "fr"):
    key = ("region", lang, _store().meta.get("data_version") or _store().meta.get("generated"))
    if key not in _agg_cache:
        g = _region_geom()
        h = _zone_result(ZoneQuery(geometry=g, name="Region", lang=lang if lang in ("fr", "en") else "fr"))["calendar"]
        n = _zone_result(ZoneQuery(geometry=g, name="Region", mode="naive", lang=lang if lang in ("fr", "en") else "fr"))["calendar"]
        _agg_cache[key] = {
            "harmonized": [{k: y[k] for k in ("fyear", "label", "total", "total_lo", "total_hi", "complete", "main_source")}
                           for y in h["years"]],
            "naive": [{k: y[k] for k in ("fyear", "label", "total", "complete")} for y in n["years"]],
            "current": h.get("current"), "summary": h["summary"], "trends": h["trends"],
            "week_labels": h["week_labels"], "area_km2": h["area_km2"]}
    return _agg_cache[key]


@app.get("/api/season/overview")
def season_overview(lang: str = "fr"):
    lang = lang if lang in ("fr", "en") else "fr"
    key = ("season", lang, _store().meta.get("data_version") or _store().meta.get("generated"))
    if key not in _agg_cache:
        gj = boundaries.load(1) or {"features": []}
        rows = []
        for f in gj["features"]:
            try:
                cal = _zone_result(ZoneQuery(geometry=f["geometry"], name=f["properties"]["name"], lang=lang))["calendar"]
            except HTTPException:
                continue
            cur = cal.get("current") or {}
            hist = [y["total"] for y in cal["years"] if y["complete"] and y["total"]]
            rows.append({"id": f["properties"]["id"], "name": f["properties"]["name"], "iso3": f["properties"]["iso3"],
                         "last": cur.get("last_status"), "cumulative": cur.get("cumulative"),
                         "cumulative_pct": cur.get("cumulative_pct"), "cumulative_status": cur.get("cumulative_status"),
                         "clim_cum_median": cur.get("clim_cum_median"), "mean_total": float(np.mean(hist)) if hist else None,
                         "onset": cal["summary"].get("onset"), "peak": cal["summary"].get("peak"),
                         "geometry": f["geometry"]})
        reg = region_summary(lang)
        _agg_cache[key] = {"regions": rows, "region": reg["current"], "week_labels": reg["week_labels"],
                           "summary": reg["summary"]}
    return _agg_cache[key]


def _forecaster():
    from ..forecast import Forecaster
    try:
        return Forecaster.get()
    except FileNotFoundError:
        raise HTTPException(503, "forecast not built — run `python -m firesync forecast`")


@app.get("/api/forecast")
def forecast_overview(lang: str = "fr"):
    lang = lang if lang in ("fr", "en") else "fr"
    return _forecaster().units_overview(lang)


@app.post("/api/zone/forecast")
def zone_forecast(qz: ZoneQuery):
    fc = _forecaster()
    geom = _validate_geom(qz.geometry)
    return fc.zone(fc.weights(geom), qz.lang, qz.name)


@lru_cache(maxsize=8)
def _hex_layer(metric: str, fyear: int | None) -> dict:
    st = _store()
    hy = st.hex_year
    complete = [y for y in st.meta.get("fire_years", []) if y > 2000][:-1]
    from ..grid import cell_area_km2
    if metric == "density":
        d = hy.filter(pl.col("fyear").is_in(complete)).group_by("h3_5").agg(pl.col("H").mean().alias("v"))
    elif metric == "year" and fyear is not None:
        d = hy.filter(pl.col("fyear") == fyear).select("h3_5", pl.col("H").alias("v"))
    elif metric == "anomaly" and fyear is not None:
        base = hy.filter(pl.col("fyear").is_in(complete)).group_by("h3_5").agg(pl.col("H").mean().alias("m"))
        d = (hy.filter(pl.col("fyear") == fyear).join(base, on="h3_5")
             .select("h3_5", (pl.col("H") / pl.col("m").clip(1, None)).alias("v")))
    elif metric == "trend":
        rows = []
        for (c,), g in hy.filter(pl.col("fyear").is_in(complete)).group_by(["h3_5"]):
            g = g.sort("fyear")
            if g["H"].sum() < 50:
                continue
            tr = indicators.trend(g["fyear"].to_list(), np.log1p(g["H"].to_numpy()).tolist())
            if tr:
                rows.append({"h3_5": c, "v": 100 * (np.exp(tr["slope"]) - 1), "p": tr["p"]})
        d = pl.DataFrame(rows) if rows else pl.DataFrame(schema={"h3_5": pl.Int64, "v": pl.Float64})
    else:
        raise HTTPException(400, "metric: density | year | anomaly | trend")
    props = {}
    for r in d.to_dicts():
        v = r["v"]
        if metric in ("density", "year"):
            v = v / cell_area_km2(r["h3_5"]) * 100  # detections / 100 km² / year
        props[int(r["h3_5"])] = {"v": round(float(v), 3), **({"p": round(r["p"], 3)} if "p" in r else {})}
    return cells_to_geojson(list(props), props)


@app.get("/api/map/hex")
def map_hex(metric: str = "density", fyear: int | None = None):
    return JSONResponse(_hex_layer(metric, fyear), headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/map/points")
def map_points(fyear: int, fweek_from: int = 0, fweek_to: int = 51, limit: int = 120000):
    st = _store()
    sw = st.meta["start_week"]
    # fire week -> calendar (year, week)
    pairs = []
    for fw in range(max(0, fweek_from), min(51, fweek_to) + 1):
        w = (sw + fw) % 52
        y = fyear + (1 if sw + fw >= 52 else 0)
        pairs.append((y, w))
    if not pairs:
        return {"n": 0, "lon": [], "lat": [], "s": [], "frp": []}
    cond = " OR ".join(f"(year={y} AND week={w})" for y, w in pairs)
    rows = st.query(f"SELECT lon, lat, sensor, frp FROM det WHERE {cond} LIMIT {int(min(limit, 250000))}")
    code = {"MODIS_T": 0, "MODIS_A": 1, "VIIRS_SNPP": 2, "VIIRS_N20": 3, "VIIRS_N21": 4}
    return {"n": len(rows), "lon": [round(r[0], 4) for r in rows], "lat": [round(r[1], 4) for r in rows],
            "s": [code.get(r[2], 9) for r in rows], "frp": [round(r[3] or 0, 1) for r in rows]}


@app.get("/api/validation")
def get_validation():
    rep = validation.load_report()
    if not rep:
        raise HTTPException(404, "validation not run yet")
    st = _store()
    return {"report": rep, "step_test": st.meta.get("step_test"), "land_cover": st.meta.get("land_cover")}


@app.post("/api/access-request")
def access_request(body: AccessRequest, _=Depends(auth.require_csrf)):
    if "@" not in body.email:
        raise HTTPException(422, "invalid email")
    with db.tx() as c:
        c.execute("INSERT INTO access_requests(name,email,org,profile,message,created_at) VALUES(?,?,?,?,?,?)",
                  (body.name, body.email.lower(), body.org, body.profile, body.message, time.time()))
    db.audit(None, "access_request", body.email)
    return {"ok": True}


# ---------------------------------------------------------------- auth
@app.post("/api/auth/login")
def login(body: Login, request: Request, response: Response, _=Depends(auth.require_csrf)):
    key = f"{request.client.host if request.client else '?'}|{body.email.lower()}"
    auth.check_rate(key)
    u = db.q1("SELECT * FROM users WHERE email=?", (body.email.strip().lower(),))
    if not u or not u["active"] or not auth.verify_password(body.password, u["pw_hash"]):
        auth.note_failure(key)
        raise HTTPException(401, "invalid credentials")
    with db.tx() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), u["id"]))
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"
    response.set_cookie(auth.COOKIE, auth.make_token(u["id"], u["role"]), httponly=True, samesite="lax",
                        secure=https, max_age=auth.SESSION_TTL, path="/")
    db.audit(u["id"], "login")
    return {"user": auth.public_user(u)}


@app.post("/api/auth/logout")
def logout(response: Response, request: Request):
    u = auth.current_user(request)
    response.delete_cookie(auth.COOKIE, path="/")
    if u:
        db.audit(u["id"], "logout")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    u = auth.current_user(request)
    return {"user": auth.public_user(u) if u else None}


@app.post("/api/auth/password")
def change_password(body: PasswordChange, u=Depends(auth.require_pro)):
    if not auth.verify_password(body.current, u["pw_hash"]):
        raise HTTPException(401, "current password incorrect")
    with db.tx() as c:
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (auth.hash_password(body.new), u["id"]))
    db.audit(u["id"], "password.change")
    return {"ok": True}


# ---------------------------------------------------------------- pro
def _zone_row(r: dict, with_geom=True) -> dict:
    out = {k: r[k] for k in ("id", "name", "kind", "category", "alert_pct", "notes", "created_at", "updated_at")}
    if with_geom:
        out["geometry"] = json.loads(r["geometry"])
    return out


@app.get("/api/pro/zones")
def pro_zones(u=Depends(auth.require_pro)):
    return [_zone_row(r) for r in db.q("SELECT * FROM zones WHERE owner_id=? AND kind!='reference' "
                                       "ORDER BY updated_at DESC", (u["id"],))]


@app.post("/api/pro/zones")
def pro_zone_create(z: ZoneIn, u=Depends(auth.require_pro)):
    geom = _validate_geom(z.geometry)
    now = time.time()
    with db.tx() as c:
        zid = c.execute("INSERT INTO zones(owner_id,name,kind,category,geometry,alert_pct,notes,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (u["id"], z.name, z.kind if z.kind != "reference" else "drawn", z.category,
                         json.dumps(geom), z.alert_pct, z.notes, now, now)).lastrowid
    db.audit(u["id"], "zone.create", z.name)
    return {"id": zid}


@app.put("/api/pro/zones/{zid}")
def pro_zone_update(zid: int, z: ZoneIn, u=Depends(auth.require_pro)):
    r = db.q1("SELECT * FROM zones WHERE id=? AND owner_id=?", (zid, u["id"]))
    if not r:
        raise HTTPException(404, "zone not found")
    with db.tx() as c:
        c.execute("UPDATE zones SET name=?,category=?,geometry=?,alert_pct=?,notes=?,updated_at=? WHERE id=?",
                  (z.name, z.category, json.dumps(_validate_geom(z.geometry)), z.alert_pct, z.notes,
                   time.time(), zid))
    return {"ok": True}


@app.delete("/api/pro/zones/{zid}")
def pro_zone_delete(zid: int, u=Depends(auth.require_pro)):
    with db.tx() as c:
        n = c.execute("DELETE FROM zones WHERE id=? AND owner_id=?", (zid, u["id"])).rowcount
    if not n:
        raise HTTPException(404, "zone not found")
    db.audit(u["id"], "zone.delete", str(zid))
    return {"ok": True}


@app.get("/api/pro/dashboard")
def pro_dashboard(lang: str = "fr", u=Depends(auth.require_pro)):
    out = []
    for r in db.q("SELECT * FROM zones WHERE owner_id=? AND kind!='reference' ORDER BY updated_at DESC LIMIT 24",
                  (u["id"],)):
        try:
            res = _zone_result(ZoneQuery(geometry=json.loads(r["geometry"]), name=r["name"], lang=lang))
        except HTTPException:
            continue
        cal = res["calendar"]
        cur = cal.get("current") or {}
        last = cur.get("last_status") or {}
        alert = bool(r["alert_pct"] is not None and last.get("pct") is not None and last["pct"] >= r["alert_pct"])
        fcz = None
        try:
            fc = _forecaster()
            z = fc.zone(fc.weights(json.loads(r["geometry"])), lang, r["name"])
            fcz = {"next2": z["next2"], "message": z["message"], "issue": z["issue"]["week_end"]}
            alert = alert or z["next2"]["risk"] == "high"
        except HTTPException:
            pass
        totals = [y["total"] for y in cal["years"] if y["complete"] and y["total"] is not None]
        out.append({"zone": _zone_row(r, with_geom=False), "current": cur.get("label"), "forecast": fcz,
                    "last": last, "cumulative": cur.get("cumulative"),
                    "cumulative_pct": cur.get("cumulative_pct"), "cumulative_status": cur.get("cumulative_status"),
                    "alert": alert, "summary": cal["summary"], "week_labels": cal["week_labels"],
                    "spark": [y["total"] for y in cal["years"] if y["total"] is not None][-15:],
                    "mean_total": float(np.mean(totals)) if totals else None,
                    "trend": (cal["trends"].get("total") or {}).get("pct_per_decade")})
    return out


@app.post("/api/pro/export/csv")
def pro_export_csv(qz: ZoneQuery, u=Depends(auth.require_pro)):
    res = _zone_result(qz)
    csv = weekly_csv(res["zd"], res["calendar"]["start_week"])
    db.audit(u["id"], "export.csv", qz.name)
    return Response(csv, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="FireSync_{qz.name}_weekly.csv"'})


@app.post("/api/pro/export/geojson")
def pro_export_geojson(qz: ZoneQuery, u=Depends(auth.require_pro)):
    res = _zone_result(qz)
    cal = res["calendar"]
    feat = {"type": "Feature", "geometry": _validate_geom(qz.geometry),
            "properties": {"name": qz.name, "summary": cal["summary"], "critical": cal["critical"],
                           "trends": cal["trends"], "current": cal.get("current"),
                           "annual": [{k: y[k] for k in ("label", "total", "total_lo", "total_hi", "onset",
                                                         "peak", "end", "duration", "main_source")}
                                      for y in cal["years"]]}}
    return JSONResponse(feat, headers={"Content-Disposition": f'attachment; filename="FireSync_{qz.name}.geojson"'})


# ---------------------------------------------------------------- admin
@app.get("/api/admin/overview")
def admin_overview(u=Depends(auth.require_admin)):
    st = _store()
    cov = _coverage(st)
    per_year = st.query("SELECT year, sensor, count(*) FROM det GROUP BY year, sensor ORDER BY year, sensor")
    files = sorted((config.RAW / "firms").rglob("*.csv"))
    return {
        "counts": {"users": db.q1("SELECT count(*) n FROM users")["n"],
                   "pros": db.q1("SELECT count(*) n FROM users WHERE role='pro'")["n"],
                   "zones": db.q1("SELECT count(*) n FROM zones WHERE kind!='reference'")["n"],
                   "reference": db.q1("SELECT count(*) n FROM zones WHERE kind='reference'")["n"],
                   "requests": db.q1("SELECT count(*) n FROM access_requests WHERE status='pending'")["n"]},
        "coverage": [{"sensor": s, "first": a, "last": b, "n": n} for s, a, b, n in cov],
        "per_year": [{"year": y, "sensor": s, "n": n} for y, s, n in per_year],
        "raw_files": len(files), "raw_mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
        "model": {k: st.meta.get(k) for k in ("generated", "start_week", "train_fire_years", "members",
                                              "theta", "kappa", "land_cover", "seconds")},
        "step_test": {k: v for k, v in (st.meta.get("step_test") or {}).items() if k != "annual"},
        "last_date": st.last_date,
        "nrt": {"configured": bool(config.FIRMS_MAP_KEY or db.get_setting("firms_map_key")),
                "snpp_end": config.SENSORS["VIIRS_SNPP"].last},
        "jobs": db.q("SELECT id,kind,status,started_at,finished_at FROM jobs ORDER BY id DESC LIMIT 8"),
    }


@app.get("/api/admin/users")
def admin_users(u=Depends(auth.require_admin)):
    return [auth.public_user(r) for r in db.q("SELECT * FROM users ORDER BY created_at DESC")]


@app.post("/api/admin/users")
def admin_user_create(body: UserIn, u=Depends(auth.require_admin)):
    pwd = body.password or secrets.token_urlsafe(10)
    try:
        uid = auth.create_user(body.email, pwd, body.role, body.name, body.org)
    except Exception as e:
        raise HTTPException(409, str(e))
    db.audit(u["id"], "user.create", f"{body.email} ({body.role})")
    return {"id": uid, "password": None if body.password else pwd}


@app.patch("/api/admin/users/{uid}")
def admin_user_patch(uid: int, body: UserPatch, u=Depends(auth.require_admin)):
    if uid == u["id"] and (body.active is False or body.role == "pro"):
        raise HTTPException(400, "you cannot demote or disable yourself")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    if "active" in fields:
        fields["active"] = int(fields["active"])
    with db.tx() as c:
        c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), uid))
    db.audit(u["id"], "user.update", f"{uid} {fields}")
    return {"ok": True}


@app.post("/api/admin/users/{uid}/reset-password")
def admin_user_reset(uid: int, u=Depends(auth.require_admin)):
    pwd = secrets.token_urlsafe(10)
    with db.tx() as c:
        n = c.execute("UPDATE users SET pw_hash=? WHERE id=?", (auth.hash_password(pwd), uid)).rowcount
    if not n:
        raise HTTPException(404, "user not found")
    db.audit(u["id"], "user.reset_password", str(uid))
    return {"password": pwd}


@app.delete("/api/admin/users/{uid}")
def admin_user_delete(uid: int, u=Depends(auth.require_admin)):
    if uid == u["id"]:
        raise HTTPException(400, "you cannot delete yourself")
    with db.tx() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
    db.audit(u["id"], "user.delete", str(uid))
    return {"ok": True}


@app.get("/api/admin/requests")
def admin_requests(u=Depends(auth.require_admin)):
    return db.q("SELECT * FROM access_requests ORDER BY status='pending' DESC, created_at DESC")


@app.post("/api/admin/requests/{rid}/{action}")
def admin_request_handle(rid: int, action: str, u=Depends(auth.require_admin)):
    r = db.q1("SELECT * FROM access_requests WHERE id=?", (rid,))
    if not r or action not in ("approve", "reject"):
        raise HTTPException(404, "not found")
    pwd = None
    if action == "approve":
        pwd = secrets.token_urlsafe(10)
        try:
            auth.create_user(r["email"], pwd, "pro", r["name"], r["org"])
        except Exception as e:
            raise HTTPException(409, f"cannot create account: {e}")
    with db.tx() as c:
        c.execute("UPDATE access_requests SET status=?, handled_by=? WHERE id=?",
                  ("approved" if action == "approve" else "rejected", u["id"], rid))
    db.audit(u["id"], f"request.{action}", r["email"])
    return {"ok": True, "password": pwd}


SETTINGS_KEYS = {"firms_map_key": str, "public_bulletins": bool, "default_lang": str, "partners": list,
                 "alert_default_pct": (int, float)}


@app.get("/api/admin/settings")
def admin_settings(u=Depends(auth.require_admin)):
    out = {k: db.get_setting(k) for k in SETTINGS_KEYS}
    out["partners"] = _partners()
    key = out.get("firms_map_key") or config.FIRMS_MAP_KEY
    out["firms_map_key"] = (key[:4] + "…" + key[-2:]) if key else ""
    out["firms_map_key_source"] = "env" if config.FIRMS_MAP_KEY else ("settings" if key else None)
    return out


def _partners() -> list[dict]:
    p = db.get_setting("partners")
    return config.DEFAULT_PARTNERS if p is None else p


def _clean_partners(items: list) -> list[dict]:
    """Admin-entered logos end up in href/src attributes: only http(s) links and
    local /assets/ or https images are accepted."""
    out = []
    for x in items[:24]:
        if not isinstance(x, dict) or not str(x.get("name", "")).strip():
            raise HTTPException(422, "each partner needs a name")
        url, logo = str(x.get("url") or "").strip(), str(x.get("logo") or "").strip()
        if url and not url.startswith(("https://", "http://")):
            raise HTTPException(422, f"bad partner URL: {url[:60]}")
        if logo and not (logo.startswith("/assets/") or logo.startswith("https://")) or ".." in logo:
            raise HTTPException(422, f"bad logo path: {logo[:60]}")
        role = x.get("role") if x.get("role") in config.PARTNER_ROLES else "partner"
        out.append({"name": str(x["name"]).strip()[:120], "url": url[:300], "logo": logo[:300],
                    "role": role, "dark": bool(x.get("dark"))})
    return out


@app.put("/api/admin/settings")
def admin_settings_put(body: dict, u=Depends(auth.require_admin)):
    for k, v in body.items():
        if k not in SETTINGS_KEYS:
            raise HTTPException(400, f"unknown setting {k}")
        if k == "firms_map_key" and (not v or "…" in str(v)):
            continue
        if not isinstance(v, SETTINGS_KEYS[k]):
            raise HTTPException(422, f"bad type for {k}")
        if k == "partners":
            v = _clean_partners(v)
        db.set_setting(k, v)
    db.audit(u["id"], "settings.update", ",".join(body))
    return {"ok": True}


@app.get("/api/admin/nrt-status")
def admin_nrt_status(u=Depends(auth.require_admin)):
    from ..ingest import firms_api
    return firms_api.key_status()


@app.post("/api/admin/jobs/{kind}")
def admin_job(kind: str, u=Depends(auth.require_admin)):
    try:
        jid = jobs.start(kind, u["id"])
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e))
    _cache.clear()
    _agg_cache.clear()
    _hex_layer.cache_clear()
    return {"id": jid}


@app.get("/api/admin/jobs")
def admin_jobs(u=Depends(auth.require_admin)):
    return db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")


@app.post("/api/admin/reference-zones")
def admin_ref_create(body: RefZoneIn, u=Depends(auth.require_admin)):
    gj = body.geojson
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    now, n = time.time(), 0
    with db.tx() as c:
        for i, f in enumerate(feats):
            geom = _validate_geom(f.get("geometry", f))
            nm = (f.get("properties") or {}).get("name") or (body.name if len(feats) == 1 else f"{body.name} {i + 1}")
            c.execute("INSERT INTO zones(owner_id,name,kind,category,geometry,public,created_at,updated_at) "
                      "VALUES(?,?,?,?,?,1,?,?)", (u["id"], nm, "reference", body.category, json.dumps(geom), now, now))
            n += 1
    db.audit(u["id"], "reference.create", f"{body.name} ({n})")
    return {"created": n}


@app.delete("/api/admin/reference-zones/{zid}")
def admin_ref_delete(zid: int, u=Depends(auth.require_admin)):
    with db.tx() as c:
        c.execute("DELETE FROM zones WHERE id=? AND kind='reference'", (zid,))
    db.audit(u["id"], "reference.delete", str(zid))
    return {"ok": True}


@app.get("/api/admin/audit")
def admin_audit(u=Depends(auth.require_admin), limit: int = 200):
    return db.q("SELECT a.*, u.email FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                "ORDER BY a.id DESC LIMIT ?", (min(limit, 1000),))


# ---------------------------------------------------------------- front-end
WEB = config.WEB
if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    f = (WEB / path).resolve()
    if path and f.is_file() and WEB.resolve() in f.parents:
        return FileResponse(f)
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
