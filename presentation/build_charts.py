"""Charts (inline SVG) and app screenshots for the pitch deck.

    python presentation/build_charts.py      (FireSync server running on :8000)
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, LogNorm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from firesync.ingest import boundaries  # noqa: E402

API = "http://127.0.0.1:8000"
A = ROOT / "presentation" / "assets"
D = json.loads((A / "deck_data.json").read_text(encoding="utf-8"))

INK, INK2, MUTED, GRID = "#1d1b19", "#52514e", "#8a847b", "#e4ddd2"
BRAND, BRAND_DARK = "#b93c17", "#7a2412"
HEAT = LinearSegmentedColormap.from_list("heat", ["#fff4dc", "#fed38a", "#f9a23f", "#e8692a", "#c23a1e", "#7d1d12"])

plt.rcParams.update({"svg.fonttype": "none", "font.family": "DejaVu Sans", "font.size": 11,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False})


def svg(fig, name):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.index("<svg"):]  # drop xml header / doctype for inlining
    (A / f"{name}.svg").write_text(s, encoding="utf-8")
    print("chart", name)


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Requested-With": "firesync"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def fr_int(x):
    return f"{x:,.0f}".replace(",", " ")


# ---------------------------------------------------------------- 1. Kédougou calendar
def kedougou_heatmap():
    gj = boundaries.load(2)
    f = next(x for x in gj["features"] if x["properties"]["name"] == "Kedougou")
    cal = post("/api/zone/calendar", {"geometry": f["geometry"], "name": "Kédougou", "lang": "fr"})["calendar"]
    years = [y for y in cal["years"] if y["label"] >= "2001"]
    M = np.array([[np.nan if v is None else v for v in y["weeks"]] for y in years], float)
    fig, ax = plt.subplots(figsize=(10.4, 5.4))
    im = ax.imshow(np.where(M > 0, np.maximum(M, 1), 1), aspect="auto", cmap=HEAT,
                   norm=LogNorm(vmin=1, vmax=np.nanpercentile(M, 99.5)), interpolation="nearest")
    im.cmap.set_bad("#f3eee6")
    ax.set_yticks(range(len(years)))
    last = len(years) - 1
    ax.set_yticklabels([y["label"] if (i % 3 == 0 and i < last - 1) or i == last else "" for i, y in enumerate(years)], fontsize=10)
    L = cal["week_labels"]
    xt = [i for i in range(52) if i % 9 == 0]
    ax.set_xticks(xt)
    ax.set_xticklabels([L[i] for i in xt], fontsize=10, rotation=0)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    # record season outline
    rec = max(range(len(years)), key=lambda i: years[i]["total"] or 0 if years[i]["complete"] else 0)
    ax.add_patch(plt.Rectangle((-0.5, rec - 0.5), 52, 1, fill=False, ec=INK, lw=1.4))
    ax.text(52.2, rec, f"record\n{fr_int(years[rec]['total'])}\ndétections", va="center", fontsize=9.5, color=INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.022, pad=0.13)
    cb.set_label("détections par semaine", fontsize=9.5, color=INK2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9, length=0)
    cb.ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fr_int(v)))
    svg(fig, "kedougou_heatmap")
    return {"record_label": years[rec]["label"], "record_total": years[rec]["total"]}


# ---------------------------------------------------------------- 2. Senegal department map
def senegal_map():
    gj = boundaries.load(2)
    dens = {d["id"]: d["density"] for d in D["departments"]}
    fig, ax = plt.subplots(figsize=(8.2, 6.2))
    bins = [0, 10, 50, 150, 300, 500, 700, 900]
    cmap = LinearSegmentedColormap.from_list("h", ["#fbefdc", "#fed38a", "#f9a23f", "#e8692a", "#c23a1e", "#7d1d12", "#4a0f08"])
    norm = BoundaryNorm(bins, cmap.N)
    from shapely.geometry import shape
    labels = {"Kedougou": "Kédougou", "Tambacounda": "Tambacounda", "Goudiry": "Goudiry", "Saraya": "Saraya",
              "Kolda": "Kolda", "Velingara": "Vélingara", "Bounkiling": "Bounkiling", "Dakar": "Dakar",
              "Linguere": "Linguère", "Podor": "Podor"}
    nudge = {"Dakar": (-0.28, 0.12), "Bounkiling": (0, -0.05), "Tambacounda": (0.3, -0.12)}
    for f in gj["features"]:
        g = shape(f["geometry"])
        p = f["properties"]
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        if p["iso3"] != "SEN":
            col, ec = "#ece6dc", "#ffffff"
        else:
            col, ec = cmap(norm(dens.get(p["id"], 0))), "#ffffff"
        ax.add_collection(PolyCollection([np.asarray(pg.exterior.coords) for pg in polys], facecolors=col,
                                         edgecolors=ec, linewidths=0.6))
        if p["iso3"] == "SEN" and p["name"] in labels:
            c = g.centroid if g.contains(g.centroid) else g.representative_point()
            dx, dy = nudge.get(p["name"], (0, 0))
            dark = dens.get(p["id"], 0) > 300
            ax.text(c.x + dx, c.y + dy, labels[p["name"]], ha="center", va="center", fontsize=9,
                    color="#ffffff" if dark else INK, fontweight="bold" if dark else "normal")
    ax.text(-15.6, 13.47, "Gambie", fontsize=8, color=MUTED, ha="center")
    ax.set_xlim(-17.65, -11.25)
    ax.set_ylim(12.25, 16.75)
    ax.set_aspect(1 / np.cos(np.radians(14.5)))
    ax.axis("off")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.04, pad=0.02, aspect=40, ticks=bins)
    cb.set_label("feux détectés par an et par 1 000 km² (moyenne 2001-2025, série harmonisée)", fontsize=9, color=INK2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8, length=0)
    svg(fig, "senegal_map")


# ---------------------------------------------------------------- 3. Sahel bars (MODIS 2024)
def sahel_bars():
    rows = sorted(D["sahel"], key=lambda r: r["n"])
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    y = np.arange(len(rows))
    cols = [BRAND if r["country"] == "Senegal" else "#c9b9a6" for r in rows]
    ax.barh(y, [r["n"] for r in rows], color=cols, height=0.62)
    for i, r in enumerate(rows):
        ax.text(r["n"] + 900, i, fr_int(r["n"]), va="center", fontsize=10, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels([r["name"] for r in rows], fontsize=11, color=INK)
    ax.tick_params(length=0)
    ax.set_xticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, max(r["n"] for r in rows) * 1.16)
    svg(fig, "sahel_bars")


# ---------------------------------------------------------------- 4. harmonised vs naive
def harmonized_vs_naive():
    r = D["region"]
    h = [y for y in r["harmonized"] if y["complete"] and y["total"]]
    n = {y["fyear"]: y["total"] for y in r["naive"] if y["complete"] and y["total"]}
    x = np.array([y["fyear"] for y in h])
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    ax.fill_between(x, [y["total_lo"] for y in h], [y["total_hi"] for y in h], color=BRAND, alpha=0.16, lw=0)
    ax.plot(x, [n.get(int(v), np.nan) for v in x], color="#9a948b", lw=2, ls=(0, (4, 3)))
    ax.plot(x, [y["total"] for y in h], color=BRAND, lw=2.6)
    ax.axvline(2012, color=INK2, lw=1, ls=":")
    ax.text(2012.2, ax.get_ylim()[1] * 0.97, "arrivée de VIIRS (2012)", fontsize=9, color=INK2, va="top")
    ax.text(x[-1] + 0.3, h[-1]["total"], "FireSync\n(harmonisé)", color=BRAND, fontsize=10, va="center", fontweight="bold")
    ax.text(2003.0, 29000, "collage naïf", color="#7d776f", fontsize=10.5)
    ax.set_xlim(x[0] - 0.5, x[-1] + 3.2)
    ax.set_ylim(0, None)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fr_int(v)))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(length=0)
    ax.spines["left"].set_visible(False)
    ax.set_ylabel("feux détectés par saison (éq. VIIRS)", fontsize=9)
    svg(fig, "harmonized_vs_naive")


# ---------------------------------------------------------------- 5. app screenshots
def screenshots():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, locale="fr-FR")
        pg.goto(f"{API}/#/forecast")
        pg.wait_for_selector("#rank tr[data-id]", timeout=90000)
        pg.wait_for_selector("#detail #c-fc svg", timeout=90000)
        pg.wait_for_timeout(6000)  # map tiles
        grid = pg.locator("#fmap").locator("xpath=ancestor::div[contains(@class,'grid')][1]")
        grid.scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)
        grid.screenshot(path=str(A / "app_forecast.png"))
        pg.locator(".fc-hero").screenshot(path=str(A / "app_forecast_hero.png"))
        br.close()
    print("screenshots ok")


if __name__ == "__main__":
    info = kedougou_heatmap()
    senegal_map()
    sahel_bars()
    harmonized_vs_naive()
    screenshots()
    (A / "chart_info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
