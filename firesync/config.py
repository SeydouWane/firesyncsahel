"""Central configuration: paths, sensors, grid and modelling constants.

Everything that a deployment may want to change can be overridden with an
environment variable (prefixed FIRESYNC_) so that the same code base runs on
Senegal, on the whole Sahel or on any other region of the globe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Serverless hosting (Vercel sets VERCEL=1): the code and the data snapshot are
# read-only, only /tmp is writable, and nothing may run in the background.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("FIRESYNC_SERVERLESS"))
DATA = Path(os.environ.get("FIRESYNC_DATA", ROOT / "data"))
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
MODELS = DATA / "models"
VALIDATION = DATA / "validation"
# writable folder for the app database (SQLite) and the local session secret
APPDB = Path(os.environ.get("FIRESYNC_APP_DIR") or ("/tmp/firesync-app" if SERVERLESS else DATA / "app"))
WEB = ROOT / "web"

for _p in (RAW, PROCESSED, MODELS, VALIDATION, APPDB):
    try:
        _p.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only file system (serverless): the data snapshot is used as is
        pass
if SERVERLESS:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


def _env_list(name: str, default: list[str]) -> list[str]:
    v = os.environ.get(name)
    return [s.strip() for s in v.split(",") if s.strip()] if v else default


# --------------------------------------------------------------------------
# Region of interest. FIRMS publishes yearly country archives without key;
# names use underscores, e.g. "Senegal", "The_Gambia", "Mali".
# --------------------------------------------------------------------------
COUNTRIES = _env_list("FIRESYNC_COUNTRIES", ["Senegal", "The_Gambia"])
# ISO3 codes used to fetch administrative units from geoBoundaries.
ADMIN_ISO3 = _env_list("FIRESYNC_ADMIN_ISO3", ["SEN", "GMB"])

FIRST_YEAR = 2000
LAST_ARCHIVE_YEAR = int(os.environ.get("FIRESYNC_LAST_ARCHIVE_YEAR", "2025"))

# NASA FIRMS API key (free, https://firms.modaps.eosdis.nasa.gov/api/map_key/)
# Needed only for near-real-time data of the running season and NOAA-21.
FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")


@dataclass(frozen=True)
class Sensor:
    code: str          # internal code
    label: str         # human label
    instrument: str    # MODIS | VIIRS
    platform: str
    first: str         # first date of the record (ISO)
    last: str | None   # last date of distribution (None = ongoing)
    country_dir: str | None  # FIRMS yearly-country folder (None = API only)
    api_sp: str | None       # FIRMS area API, standard processing
    api_nrt: str | None      # FIRMS area API, near real time


SENSORS: dict[str, Sensor] = {
    "MODIS_T": Sensor("MODIS_T", "MODIS Terra", "MODIS", "Terra", "2000-11-01", None,
                      "modis", "MODIS_SP", "MODIS_NRT"),
    "MODIS_A": Sensor("MODIS_A", "MODIS Aqua", "MODIS", "Aqua", "2002-07-04", None,
                      "modis", "MODIS_SP", "MODIS_NRT"),
    "VIIRS_SNPP": Sensor("VIIRS_SNPP", "VIIRS Suomi NPP", "VIIRS", "Suomi NPP", "2012-01-20",
                         "2026-11-01", "viirs-snpp", "VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "VIIRS_N20": Sensor("VIIRS_N20", "VIIRS NOAA-20", "VIIRS", "NOAA-20", "2018-04-01", None,
                        "viirs-jpss1", "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    "VIIRS_N21": Sensor("VIIRS_N21", "VIIRS NOAA-21", "VIIRS", "NOAA-21", "2024-01-17", None,
                        None, "VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"),
}

# The harmonised series is expressed in "VIIRS S-NPP equivalent detections":
# S-NPP is the longest VIIRS record and MODIS will end first, so the future of
# the series is VIIRS and the past is converted towards it.
REFERENCE_SENSOR = "VIIRS_SNPP"


@dataclass(frozen=True)
class GridConfig:
    model_res: int = 5   # H3 resolution of the harmonisation model (~253 km²)
    fine_res: int = 7    # H3 resolution of pre-aggregates used by queries (~5 km²)
    coarse_res: int = 3  # H3 resolution used as a "department-size" validation scale


GRID = GridConfig()

WEEKS_PER_YEAR = 52  # week index = min(day_of_year // 7, 51); week 51 has 8-9 days


@dataclass(frozen=True)
class ModelConfig:
    # Overlap years used to learn MODIS -> VIIRS. Terra (2020+) and Aqua (2022+)
    # orbits drift towards other overpass times; years after the drift onset are
    # kept out of training and used as an out-of-window test instead.
    train_fire_years: tuple[int, ...] = tuple(range(2012, 2021))
    test_fire_years: tuple[int, ...] = tuple(range(2021, 2025))
    n_bootstrap: int = 8
    overpass_tolerance_min: int = 60
    eb_prior_strength: float = 20.0  # in MODIS-detection units
    interval: float = 0.90
    random_state: int = 42
    gbm_params: dict = field(default_factory=lambda: dict(
        loss="poisson", learning_rate=0.08, max_iter=220, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, early_stopping=True,
        n_iter_no_change=15, validation_fraction=0.1,
    ))
    # cell-weeks with no detection at all (target, inputs, neighbouring weeks)
    # are subsampled for training and re-weighted: unbiased, ~3x faster
    dead_keep: float = 0.15


MODEL = ModelConfig()


@dataclass(frozen=True)
class SeasonConfig:
    onset_q: float = 0.10   # onset = week where cumulative activity reaches 10 %
    end_q: float = 0.90     # end   = week where cumulative activity reaches 90 %
    critical_share: tuple[float, ...] = (0.5, 0.8)
    anomaly_hi: float = 90.0
    anomaly_lo: float = 10.0


SEASON = SeasonConfig()

# Secret used to sign session tokens. On a server it is generated and persisted
# on first run; on serverless hosting it MUST come from FIRESYNC_SECRET, otherwise
# each instance signs with its own key and sessions break between instances.
_secret_file = APPDB / ".secret"
if os.environ.get("FIRESYNC_SECRET"):
    SECRET = os.environ["FIRESYNC_SECRET"]
else:
    import secrets
    try:
        if not _secret_file.exists():
            _secret_file.write_text(secrets.token_hex(32))
        SECRET = _secret_file.read_text().strip()
    except OSError:
        SECRET = secrets.token_hex(32)
    if SERVERLESS:
        import logging
        logging.getLogger(__name__).warning("FIRESYNC_SECRET is not set: sessions will not survive cold starts")

# Postgres connection string (Vercel Postgres / Neon / Supabase…). When set, users,
# zones and settings are stored there instead of the local SQLite file.
DATABASE_URL = (os.environ.get("FIRESYNC_DATABASE_URL") or os.environ.get("DATABASE_URL")
                or os.environ.get("POSTGRES_URL") or "")

# Logos shown in the public space (editable in Admin › Paramètres). "role" picks the caption,
# "dark" puts a light-on-transparent logo on a dark tile.
DEFAULT_PARTNERS = [
    {"name": "NASA Space Apps Challenge · Dakar", "url": "https://www.spaceappschallenge.org/",
     "logo": "/assets/partners/space-apps.png", "role": "challenge", "dark": True},
    {"name": "SENSAT — Projet Spatial du Sénégal", "url": "",
     "logo": "/assets/partners/sensat.png", "role": "partner", "dark": False},
]
PARTNER_ROLES = ("challenge", "partner", "data")

FIRMS_ACK = {
    "en": ("We acknowledge the use of data and imagery from LANCE FIRMS operated by "
           "NASA's Goddard Space Flight Center Earth Science Data and Information System "
           "(ESDIS) with funding provided by NASA Headquarters."),
    "fr": ("Nous remercions LANCE FIRMS, opéré par le système ESDIS (Earth Science Data and "
           "Information System) du Goddard Space Flight Center de la NASA avec un financement "
           "du siège de la NASA, pour l'utilisation de ses données et images."),
}
