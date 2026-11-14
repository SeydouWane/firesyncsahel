"""Assemble the pitch deck (slides_template.html -> slides.html) and print it to PDF.

    python presentation/build_data.py     # facts from the FireSync data (server on :8000)
    python presentation/build_charts.py   # charts + app screenshots
    python presentation/render.py         # -> presentation/FireSync_Sahel_NASA_Space_Apps_Dakar.pdf
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = HERE / "assets"
D = json.loads((A / "deck_data.json").read_text(encoding="utf-8"))
INFO = json.loads((A / "chart_info.json").read_text(encoding="utf-8"))
PDF = HERE / "FireSync_Sahel_NASA_Space_Apps_Dakar.pdf"
NB = " "  # narrow no-break space (French thousands separator)
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def n(x, dec=0):
    s = f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")
    return s.replace(" ", NB)


def nround(x, step):
    return n(round(x / step) * step)


def flame():
    # static version of the app's animated logo (hexagon, flame, orbiting satellite)
    return """<svg class="flame" viewBox="0 0 100 104" aria-hidden="true">
  <defs>
    <linearGradient id="lh" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8f2b13"/><stop offset="1" stop-color="#4a150b"/></linearGradient>
    <linearGradient id="lf" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#c23a1e"/><stop offset=".55" stop-color="#f28a33"/><stop offset="1" stop-color="#ffd27a"/></linearGradient>
    <linearGradient id="li" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ffb347"/><stop offset="1" stop-color="#fff3c4"/></linearGradient>
    <radialGradient id="lg" cx="50%" cy="62%" r="50%"><stop offset="0" stop-color="#ff9a3c" stop-opacity=".55"/><stop offset="1" stop-color="#ff9a3c" stop-opacity="0"/></radialGradient>
    <clipPath id="lc"><path d="M50 6 89 28.5v45L50 96 11 73.5v-45z"/></clipPath>
  </defs>
  <path d="M50 6 89 28.5v45L50 96 11 73.5v-45z" fill="url(#lh)"/>
  <g clip-path="url(#lc)" fill="none" stroke="#ffb27a" stroke-width=".8" opacity=".7">
    <path d="M24 22l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/><path d="M60 22l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/>
    <path d="M16 50l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/><path d="M68 50l8-4.6 8 4.6v9.2l-8 4.6-8-4.6z"/></g>
  <circle cx="50" cy="62" r="30" fill="url(#lg)"/>
  <path d="M50 24c5 11 20 17 20 36a20 20 0 0 1-40 0c0-10 6-15 9-23 2 6 5 9 8 10-2-9 0-16 3-23z" fill="url(#lf)"/>
  <path d="M50 50c3 6 10 9 10 17a10 10 0 0 1-20 0c0-5 3-8 5-12 1 3 2 4 4 5-1-4 0-7 1-10z" fill="url(#li)"/>
  <circle cx="44" cy="36" r="1.6" fill="#ffd27a"/><circle cx="56" cy="31" r="1.3" fill="#ffe7a6"/><circle cx="50" cy="27" r="1.1" fill="#fff3c4"/>
  <ellipse cx="50" cy="52" rx="44" ry="15" fill="none" stroke="#ffd27a" stroke-opacity=".5" stroke-width="1" transform="rotate(-18 50 52)"/>
  <g transform="rotate(-18 50 52) translate(92 50)"><rect x="-3" y="-2.5" width="6" height="5" rx="1" fill="#fff"/>
    <rect x="-9" y="-1.2" width="5" height="2.4" fill="#9ec5f4"/><rect x="4" y="-1.2" width="5" height="2.4" fill="#9ec5f4"/></g>
</svg>"""


def inline_svg(name: str) -> str:
    s = (A / f"{name}.svg").read_text(encoding="utf-8")
    p = name[:3] + "_"
    # make ids unique across the several inlined charts
    s = re.sub(r'id="([^"]+)"', rf'id="{p}\1"', s)
    s = re.sub(r"url\(#([^)]+)\)", rf"url(#{p}\1)", s)
    s = re.sub(r'xlink:href="#([^"]+)"', rf'xlink:href="#{p}\1"', s)
    s = re.sub(r'(<svg[^>]*?)\swidth="[^"]+"\s+height="[^"]+"', r"\1", s, count=1)
    return s


def foot(page: str, src: str) -> str:
    return (f'<div class="foot"><span class="logo dark"><img src="../web/assets/partners/space-apps.png" alt="NASA Space Apps Challenge"></span>'
            f'<span class="logo"><img src="../web/assets/partners/sensat.png" alt="SENSAT"></span>'
            f'<span class="src">{src}</span><span class="page">FireSync Sahel · {page} / 7</span></div>')


def values() -> dict:
    deps = {d["name"]: d for d in D["departments"]}
    k = deps["Kedougou"]
    L = k["labels"]
    tot_det = sum(d["mean_total"] for d in D["departments"])
    se = [d for d in D["departments"] if d["region"] in ("Tambacounda", "Kedougou", "Kolda", "Sedhiou")]
    ba = D["senegal_ba"]["km2"]
    sen_area = 196722  # km²
    fc = D["forecast"]
    sar = next(u for u in fc["units"] if u["name"] == "Saraya")
    iss = date.fromisoformat(fc["issue"]["week_end"])
    return {
        "ked_frac": n(100 * k["ba_frac"]), "ked_ha": nround(k["ba_mean_km2"] * 100, 1000), "ked_area": n(k["area_km2"]),
        "ked_mean": nround(k["mean_total"], 100), "ked_density": n(k["density"]),
        "ked_record": n(INFO["record_total"]), "ked_record_label": INFO["record_label"],
        "ked_onset": L[k["onset"]], "ked_peak": L[k["peak"]], "ked_end": L[k["end"]],
        "sen_mha": n(sum(ba) / len(ba) / 1e4, 1), "sen_pct": n(100 * sum(ba) / len(ba) / sen_area),
        "se_share": n(100 * sum(d["mean_total"] for d in se) / tot_det),
        "se_area": n(100 * sum(d["area_km2"] for d in se) / sen_area),
        "sen_det": nround(tot_det, 500),
        "issue_end": f"{iss.day} {MONTHS[iss.month - 1]} {iss.year}",
        "saraya_mu": n(sar["next2"]["mu"]), "saraya_ratio": n(sar["next2"]["ratio"], 1),
        "logo_sa": "../web/assets/partners/space-apps.png", "logo_sensat": "../web/assets/partners/sensat.png",
    }


def main():
    import polars as pl
    v = values()
    det = HERE.parent / "data" / "processed" / "det_serving.parquet"
    n_rows = pl.scan_parquet(det).select(pl.len()).collect().item()
    v["n_det"] = n(n_rows / 1e6, 1) + NB + "M"
    html = (HERE / "slides_template.html").read_text(encoding="utf-8")
    html = html.replace("{{flame}}", flame())
    html = re.sub(r"\{\{svg:([a-z_]+)\}\}", lambda m: inline_svg(m.group(1)), html)
    html = re.sub(r"\{\{foot:(\d):(.*?)\}\}", lambda m: foot(m.group(1), m.group(2)), html, flags=re.S)
    for key, val in v.items():
        html = html.replace("{{" + key + "}}", str(val))
    left = re.findall(r"\{\{[^}]+\}\}", html)
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    out = HERE / "slides.html"
    out.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        pg.goto(out.as_uri(), wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(800)
        pg.pdf(path=str(PDF), width="1600px", height="900px", print_background=True,
               margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        # previews for visual checks
        prev = HERE / "preview"
        prev.mkdir(exist_ok=True)
        for i, el in enumerate(pg.locator("section.slide").all(), 1):
            el.screenshot(path=str(prev / f"slide_{i}.png"))
        br.close()
    print("ok", PDF)


if __name__ == "__main__":
    main()
