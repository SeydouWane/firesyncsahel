"""Authenticated downloads from NASA Earthdata (LP DAAC cloud).

Credentials are read, in this order, from
  * the environment: EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or EARTHDATA_TOKEN)
  * the user's ~/.netrc (machine urs.earthdata.nasa.gov)
and are never written to disk by FireSync.
"""
from __future__ import annotations

import netrc
import os
from pathlib import Path

import requests

URS = "urs.earthdata.nasa.gov"


class _EarthdataSession(requests.Session):
    """Keeps the Authorization header only when redirected to/within URS."""

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        url = prepared_request.url
        if "Authorization" in headers:
            orig = requests.utils.urlparse(response.request.url).hostname
            redir = requests.utils.urlparse(url).hostname
            if orig != redir and redir != URS and orig != URS:
                del headers["Authorization"]


def _credentials() -> tuple[str, str] | None:
    u, p = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if u and p:
        return u, p
    try:
        auth = netrc.netrc().authenticators(URS)
        if auth:
            return auth[0], auth[2]
    except (FileNotFoundError, netrc.NetrcParseError):
        pass
    return None


def session() -> requests.Session:
    s = _EarthdataSession()
    token = os.environ.get("EARTHDATA_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    else:
        cred = _credentials()
        if not cred:
            raise RuntimeError("Earthdata credentials missing: set EARTHDATA_USERNAME / "
                               "EARTHDATA_PASSWORD, EARTHDATA_TOKEN or ~/.netrc")
        s.auth = cred
    return s


def download(url: str, dest: Path, s: requests.Session | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    s = s or session()
    with s.get(url, stream=True, timeout=300, allow_redirects=True) as r:
        if r.status_code == 401:
            raise RuntimeError("Earthdata login refused (401): check username/password and "
                               "that the LP DAAC application is authorised in your profile")
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.replace(dest)
    return dest
