"""Command line: python -m firesync <command>

  download      FIRMS yearly country archives (no key needed)
  nrt           near-real-time + NOAA-21 via FIRMS API (needs FIRMS_MAP_KEY)
  process       raw CSV -> detections + hexagon aggregates
  landcover     land-cover fractions (MCD12Q1 if Earthdata login, else ESA CCI)
  burned        MCD64A1 weekly burned area (independent validation)
  boundaries    administrative units (geoBoundaries)
  validate      leave-one-year-out validation of the harmonisation
  fit           fit final models and write serving tables
  build         all of the above, in order
  create-user   create an account:  create-user EMAIL --role admin|pro [--name N]
  serve         run the web platform (FastAPI + static front-end)
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys


def refresh_all(nrt: bool = True) -> dict:
    """Near-real-time cycle: new FIRMS data -> detections -> serving tables -> forecast.
    The MODIS harmonisation model is not refitted (it only concerns MODIS-only weeks)."""
    from . import forecast, processing
    from .harmonize import context, pipeline, validate
    from .ingest import firms_api
    out = {}
    if nrt:
        out["nrt"] = firms_api.update()
    out["detections"] = processing.run()["detections"]
    ctx = context.build(rebuild_pairs=True)
    out["serving"] = pipeline.refresh(ctx)
    try:
        validate.recalibrate(ctx)  # refreshes NOAA-20 / NOAA-21 continuity checks
    except Exception as e:  # validation cache missing: keep previous kappas
        out["recalibrate"] = str(e)
    fc = forecast.build(run_validation=not forecast.OUT_JSON.exists())
    out["forecast_issue"] = fc["issue"]["week_start"]
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="firesync", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("download", "nrt", "process", "landcover", "burned", "boundaries",
              "fit", "build", "recalibrate", "refresh", "forecast", "ndvi"):
        sub.add_parser(c)
    v = sub.add_parser("validate")
    v.add_argument("--no-fit", action="store_true", help="validate only, then recalibrate serving metadata")
    u = sub.add_parser("create-user")
    u.add_argument("email")
    u.add_argument("--role", default="pro", choices=["admin", "pro"])
    u.add_argument("--name", default="")
    u.add_argument("--password", default=None, help="omit to be prompted / auto-generate")
    u.add_argument("--generate", action="store_true", help="generate a random password, no prompt")
    hp = sub.add_parser("hash-password", help="print the scrypt hash for FIRESYNC_ADMIN_PASSWORD_HASH")
    hp.add_argument("--password", default=None, help="omit to read it from standard input")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.cmd in ("download", "build"):
        from .ingest import firms_country
        res = firms_country.download_all()
        print(f"FIRMS archives: {sum(r[0] in ('ok', 'cached') for r in res)} files")
    if a.cmd in ("nrt", "build"):
        from .ingest import firms_api
        print(firms_api.update())
    if a.cmd in ("process", "build"):
        from . import processing
        print(json.dumps(processing.run(), indent=1, default=str)[:2000])
    if a.cmd in ("landcover", "build"):
        from .ingest import landcover
        print(landcover.build())
    if a.cmd in ("burned", "build"):
        from .ingest import burned_area
        try:
            print(burned_area.build())
        except Exception as e:
            print(f"MCD64A1 skipped: {e}")
    if a.cmd in ("boundaries", "build"):
        from .ingest import boundaries
        print(boundaries.build())
    if a.cmd in ("ndvi", "build"):
        from .ingest import ndvi
        try:
            print(ndvi.build())
        except Exception as e:
            print(f"MOD13A1 NDVI skipped: {e}")
    if a.cmd in ("validate", "fit", "build"):
        from .harmonize import context, pipeline, validate
        ctx = context.build(rebuild_pairs=a.cmd == "build")
        rep = validate.run(ctx) if a.cmd in ("validate", "build") else validate.load_report()
        if a.cmd == "validate" and getattr(a, "no_fit", False):
            validate.recalibrate(ctx)
        else:
            meta = pipeline.fit_and_write(ctx, rep)
            print(json.dumps({k: v for k, v in meta.get("step_test", {}).items() if k != "annual"},
                             indent=1, default=float))
    if a.cmd == "refresh":
        print(refresh_all())
    if a.cmd in ("forecast", "build"):
        from . import forecast
        r = forecast.build(run_validation=True)
        v = r["validation"]
        print(f"forecast issued {r['issue']['week_start']} | features {r['feature_set']} | zone 4-wk skill "
              f"vs climatology {100 * v['zone_4wk']['ml']['skill_vs_clim']:.1f}% | BSS {v['above_normal']['bss_ml']:.3f} "
              f"(raw {v['above_normal']['bss_raw']:.3f}) | AUC {v['above_normal']['auc_ml']:.3f}")
        print(json.dumps(v.get("ablation"), indent=1))
    if a.cmd == "recalibrate":
        from .harmonize import context, validate
        rep = validate.recalibrate(context.build())
        g = rep["variants"]["TA"]["gbm"]
        print(f"kappa={g['kappa']:.2f} coverage={g['loyo']['zone_week']['coverage90']:.3f}")
    if a.cmd == "hash-password":
        from .api.auth import hash_password
        pwd = a.password if a.password is not None else sys.stdin.readline().rstrip("\r\n")
        pwd = pwd.lstrip("﻿")  # Windows PowerShell pipes text with a UTF-8 BOM
        if len(pwd) < 8:
            sys.exit("password must be at least 8 characters")
        print(hash_password(pwd))
    if a.cmd == "create-user":
        from .api import auth
        pwd = a.password
        generated = False
        if not pwd:
            if sys.stdin.isatty() and sys.stdout.isatty() and "--generate" not in sys.argv:
                pwd = getpass.getpass("Mot de passe / password (vide = généré): ")
            if not pwd:
                import secrets
                pwd = secrets.token_urlsafe(12)
                generated = True
        auth.create_user(a.email, pwd, role=a.role, name=a.name or a.email.split("@")[0])
        print(f"user {a.email} created with role {a.role}")
        if generated:
            print(f"generated password: {pwd}")
    if a.cmd == "serve":
        import uvicorn
        from . import config
        uvicorn.run("firesync.api.app:app", host=a.host, port=a.port, reload=a.reload,
                    reload_dirs=[str(config.ROOT / "firesync")] if a.reload else None)


if __name__ == "__main__":
    main()
