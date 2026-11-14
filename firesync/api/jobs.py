"""Background data jobs launched from the admin space (one at a time)."""
from __future__ import annotations

import io
import logging
import threading
import time
import traceback

from .. import config
from . import db

_running = threading.Lock()
SERVERLESS_MSG = ("Les traitements de données ne tournent pas sur l'hébergement serverless (Vercel) : "
                  "lancez `python -m firesync refresh` sur un poste, puis publiez les données (git push) "
                  "pour redéployer.")
KINDS = ["refresh", "download", "nrt", "process", "landcover", "burned", "boundaries", "validate", "fit",
         "forecast", "reload"]


class _Capture(logging.Handler):
    def __init__(self, job_id):
        super().__init__(logging.INFO)
        self.job_id = job_id
        self.buf = io.StringIO()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.buf.write(self.format(record) + "\n")
        with db.tx() as c:
            c.execute("UPDATE jobs SET log=? WHERE id=?", (self.buf.getvalue()[-20000:], self.job_id))


def _run(kind: str):
    from ..series import Store
    from ..forecast import Forecaster
    if kind == "refresh":
        from ..__main__ import refresh_all
        r = refresh_all()
        Store.reset(); Forecaster.reset()
        return str(r)
    if kind == "forecast":
        from .. import forecast
        r = forecast.build(run_validation=True)
        Forecaster.reset()
        return f"forecast issued {r['issue']['week_start']}"
    if kind == "download":
        from ..ingest import firms_country
        r = firms_country.download_all()
        return f"{sum(x[0] in ('ok', 'cached') for x in r)} files"
    if kind == "nrt":
        from ..ingest import firms_api
        return str(firms_api.update())
    if kind == "process":
        from .. import processing
        return str(processing.run()["detections"]) + " detections"
    if kind == "landcover":
        from ..ingest import landcover
        return str(landcover.build())
    if kind == "burned":
        from ..ingest import burned_area
        return str(burned_area.build())
    if kind == "boundaries":
        from ..ingest import boundaries
        return str(boundaries.build())
    if kind in ("validate", "fit"):
        from ..harmonize import context, pipeline, validate
        ctx = context.build(rebuild_pairs=True)
        rep = validate.run(ctx) if kind == "validate" else validate.load_report()
        pipeline.fit_and_write(ctx, rep)
        Store.reset()
        return "models written"
    if kind == "reload":
        Store.reset(); Forecaster.reset()
        Store.get()
        return "serving tables reloaded"
    raise ValueError(kind)


def start(kind: str, user_id: int) -> int:
    if kind not in KINDS:
        raise ValueError(f"unknown job {kind}")
    if config.SERVERLESS and kind != "reload":
        raise RuntimeError(SERVERLESS_MSG)
    if not _running.acquire(blocking=False):
        raise RuntimeError("a job is already running")
    with db.tx() as c:
        job_id = c.execute("INSERT INTO jobs(kind,status,created_by,started_at) VALUES(?,?,?,?)",
                           (kind, "running", user_id, time.time())).lastrowid

    def target():
        h = _Capture(job_id)
        root = logging.getLogger("firesync")
        root.addHandler(h)
        root.setLevel(logging.INFO)
        try:
            msg = _run(kind)
            status = "done"
        except Exception as e:  # report to the admin UI
            msg = f"{e}\n{traceback.format_exc()[-3000:]}"
            status = "failed"
        finally:
            root.removeHandler(h)
            _running.release()
        with db.tx() as c:
            c.execute("UPDATE jobs SET status=?, finished_at=?, log=? WHERE id=?",
                      (status, time.time(), (h.buf.getvalue() + "\n" + msg)[-20000:], job_id))
        db.audit(user_id, f"job.{kind}.{status}", msg[:300])

    threading.Thread(target=target, daemon=True).start()
    return job_id
