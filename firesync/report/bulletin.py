"""Bilingual (FR/EN) PDF fire-season bulletin for a zone."""
from __future__ import annotations

import io
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)

from .. import config  # noqa: E402


def _symbol_font() -> str | None:
    """Helvetica has no ▲ ▼ ● → glyphs: draw those with DejaVu Sans (shipped with matplotlib)."""
    try:
        from pathlib import Path
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        pdfmetrics.registerFont(TTFont("DejaVu", str(path)))
        return "DejaVu"
    except Exception:
        return None


SYM_FONT = _symbol_font()
_SYMBOLS = "▲▼●→≥≤"


def _g(text: str) -> str:
    """Wrap the symbols Helvetica cannot draw in a DejaVu <font> tag (Paragraph markup)."""
    if not SYM_FONT:
        return text
    return "".join(f"<font name='{SYM_FONT}'>{ch}</font>" if ch in _SYMBOLS else ch for ch in str(text))


INK, INK2, MUTED, GRID = "#1d1b19", "#52514e", "#898781", "#e1e0d9"
SRC_COL = {"VIIRS_SNPP": "#2a78d6", "TA": "#eb6834", "T": "#eb6834", "A": "#eb6834",
           "N20": "#1baf7a", "N21": "#1baf7a"}
HEAT = LinearSegmentedColormap.from_list(
    "fs_heat", ["#fff4dc", "#fed38a", "#f9a23f", "#e8692a", "#c23a1e", "#7d1d12"])
STATUS = {"above_p90": ("#d03b3b", "▲▲"), "p75_p90": ("#fab219", "▲"), "normal": ("#0ca30c", "●"),
          "p10_p25": ("#898781", "▼"), "below_p10": ("#898781", "▼▼"), "nodata": ("#898781", "–"),
          "offseason": ("#898781", "·"), "few": ("#898781", "–")}

T = {
    "fr": {
        "title": "Bulletin de saison des feux", "zone": "Zone", "area": "Surface",
        "generated": "Édité le", "data_to": "Données jusqu'au", "unit": "détections VIIRS S-NPP équivalentes",
        "key": "Indicateurs clés (médianes des saisons complètes)", "onset": "Début de saison",
        "peak": "Pic", "end": "Fin de saison", "duration": "Durée", "weeks": "semaines",
        "crit50": "Semaines critiques (50 % de l'activité)", "crit80": "Période active (80 % de l'activité)",
        "trend_total": "Tendance de l'activité annuelle", "trend_onset": "Tendance du début de saison",
        "per_decade": "par décennie", "signif": "significative", "nonsignif": "non significative",
        "current": "Saison en cours", "cum": "Cumul depuis le début de la saison",
        "lastweek": "Dernière semaine disponible", "calendar": "Calendrier harmonisé (années de feu × semaines)",
        "clim": "Saison moyenne et dispersion historique", "annual": "Total annuel harmonisé (intervalle 90 %)",
        "anoms": "Années anormales", "method": "Méthode, sources et limites",
        "status": {"above_p90": "au-dessus du 90e percentile", "p75_p90": "entre les 75e et 90e percentiles",
                   "normal": "dans la normale (25e–75e percentile)", "p10_p25": "sous le 25e percentile",
                   "below_p10": "sous le 10e percentile", "nodata": "pas de donnée",
                   "offseason": "hors saison", "few": "activité trop faible pour comparer"},
        "src": {"VIIRS_SNPP": "VIIRS S-NPP observé", "TA": "MODIS → S-NPP (modèle)", "T": "MODIS → S-NPP (modèle)",
                "A": "MODIS → S-NPP (modèle)", "N20": "NOAA-20 → S-NPP", "N21": "NOAA-21 → S-NPP"},
        "median": "médiane", "band50": "25e–75e percentile", "band80": "10e–90e percentile",
        "high": "forte activité", "low": "faible activité", "early": "début précoce", "late": "début tardif",
        "method_txt": (
            "Les détections de feux actifs MODIS (Terra, Aqua, 2000→) et VIIRS 375 m (S-NPP 2012→, NOAA-20, "
            "NOAA-21) sont converties en une série unique exprimée en détections VIIRS S-NPP équivalentes. "
            "La conversion est apprise sur les années où MODIS et VIIRS observent ensemble, cellule hexagonale "
            "par cellule, selon la saison et l'occupation du sol (MODIS MCD12Q1), avec appariement des "
            "passages quasi simultanés Aqua/S-NPP. Chaque valeur modélisée est accompagnée d'un intervalle à "
            "90 % calibré en retirant des années entières de l'apprentissage. Après l'arrêt de la diffusion "
            "S-NPP (1er novembre 2026), NOAA-20 et NOAA-21 sont ramenés à l'équivalent S-NPP."),
        "limits": ("Les détections satellitaires ne voient pas les feux sous couvert nuageux ou trop petits, "
                   "et les satellites MODIS dérivent depuis 2020–2022. Le bulletin décrit l'activité de feu "
                   "détectée, pas les surfaces brûlées."),
        "validation": "Validation (années retirées)", "pct": "percentile",
    },
    "en": {
        "title": "Fire season bulletin", "zone": "Zone", "area": "Area", "generated": "Issued on",
        "data_to": "Data up to", "unit": "VIIRS S-NPP-equivalent detections",
        "key": "Key indicators (medians over complete seasons)", "onset": "Season onset", "peak": "Peak",
        "end": "Season end", "duration": "Duration", "weeks": "weeks",
        "crit50": "Critical weeks (50% of activity)", "crit80": "Active period (80% of activity)",
        "trend_total": "Trend in annual activity", "trend_onset": "Trend in season onset",
        "per_decade": "per decade", "signif": "significant", "nonsignif": "not significant",
        "current": "Current season", "cum": "Cumulative since season start",
        "lastweek": "Latest available week", "calendar": "Harmonised calendar (fire years × weeks)",
        "clim": "Mean season and historical spread", "annual": "Harmonised annual total (90% interval)",
        "anoms": "Anomalous years", "method": "Method, sources and limitations",
        "status": {"above_p90": "above the 90th percentile", "p75_p90": "between the 75th and 90th percentiles",
                   "normal": "within normal (25th–75th percentile)", "p10_p25": "below the 25th percentile",
                   "below_p10": "below the 10th percentile", "nodata": "no data", "offseason": "off-season",
                   "few": "too little activity to compare"},
        "src": {"VIIRS_SNPP": "VIIRS S-NPP observed", "TA": "MODIS → S-NPP (model)", "T": "MODIS → S-NPP (model)",
                "A": "MODIS → S-NPP (model)", "N20": "NOAA-20 → S-NPP", "N21": "NOAA-21 → S-NPP"},
        "median": "median", "band50": "25th–75th percentile", "band80": "10th–90th percentile",
        "high": "high activity", "low": "low activity", "early": "early onset", "late": "late onset",
        "method_txt": (
            "MODIS (Terra, Aqua, 2000→) and VIIRS 375 m (S-NPP 2012→, NOAA-20, NOAA-21) active-fire detections "
            "are merged into a single series expressed in VIIRS S-NPP-equivalent detections. The conversion is "
            "learnt over the years when MODIS and VIIRS observe together, per hexagonal cell, by season and land "
            "cover (MODIS MCD12Q1), using near-simultaneous Aqua/S-NPP overpass pairs. Every modelled value "
            "carries a 90% interval calibrated by holding out entire years. After the end of S-NPP distribution "
            "(1 November 2026), NOAA-20 and NOAA-21 are converted to S-NPP equivalent."),
        "limits": ("Satellites miss fires under clouds or too small to detect, and the MODIS platforms have been "
                   "drifting since 2020–2022. The bulletin describes detected fire activity, not burned area."),
        "validation": "Validation (held-out years)", "pct": "percentile",
    },
}


def _png(fig, dpi=200) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _style_axes(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED, labelsize=7, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _ticks(labels, every=4):
    idx = list(range(0, len(labels), every))
    return idx, [labels[i] for i in idx]


def heatmap_png(cal: dict, t: dict) -> io.BytesIO:
    yrs = cal["years"]
    M = np.array([[np.nan if v is None else v for v in y["weeks"]] for y in yrs], dtype=float)
    vmax = np.nanpercentile(M, 99) if np.isfinite(M).any() else 1
    fig, ax = plt.subplots(figsize=(7.2, 0.17 * len(yrs) + 0.9))
    Mp = np.where(np.isfinite(M), np.maximum(M, 1.0), np.nan)
    im = ax.imshow(Mp, aspect="auto", cmap=HEAT, norm=LogNorm(vmin=1.0, vmax=max(vmax, 2)),
                   interpolation="nearest")
    ax.set_yticks(range(len(yrs)))
    ax.set_yticklabels([y["label"] for y in yrs], fontsize=6, color=INK2)
    i, l = _ticks(cal["week_labels"])
    ax.set_xticks(i); ax.set_xticklabels(l, fontsize=6.5, color=MUTED)
    for k, y in enumerate(yrs):  # source strip, inside the axes, left of week 0
        ax.add_patch(plt.Rectangle((-2.1, k - 0.42), 0.9, 0.84, color=SRC_COL.get(y["main_source"], MUTED),
                                   alpha=1 if y["complete"] else 0.45))
    ax.set_xlim(-2.4, 51.5)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.ax.tick_params(labelsize=6, colors=MUTED)
    cb.outline.set_visible(False)
    cb.set_label(t["unit"] + " / sem." if t is T["fr"] else t["unit"] + " / week", fontsize=6.5, color=INK2)
    return _png(fig)


def clim_png(cal: dict, t: dict) -> io.BytesIO:
    c = cal["climatology"]
    x = np.arange(52)
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    _style_axes(ax)
    if c:
        f = lambda k: np.array([np.nan if v is None else v for v in c[k]], dtype=float)
        ax.fill_between(x, f("p10"), f("p90"), color="#c3c2b7", alpha=0.35, linewidth=0, label=t["band80"])
        ax.fill_between(x, f("p25"), f("p75"), color="#898781", alpha=0.35, linewidth=0, label=t["band50"])
        ax.plot(x, f("p50"), color=INK2, linewidth=1.6, label=t["median"])
    cur = cal.get("current")
    if cur and cur["weeks"]:
        cx = [w["fweek"] for w in cur["weeks"]]
        cy = [w["value"] for w in cur["weeks"]]
        ax.plot(cx, cy, color="#2a78d6", linewidth=2, label=f"{t['current']} {cur['label']}")
        ax.plot(cx[-1:], cy[-1:], "o", color="#2a78d6", markersize=4)
    i, l = _ticks(cal["week_labels"])
    ax.set_xticks(i); ax.set_xticklabels(l)
    ax.set_xlim(0, 51)
    ax.legend(fontsize=6.5, frameon=False, loc="upper right")
    return _png(fig)


def annual_png(cal: dict, t: dict) -> io.BytesIO:
    yrs = [y for y in cal["years"] if y["total"] is not None]
    x = np.arange(len(yrs))
    v = np.array([y["total"] for y in yrs])
    lo = np.array([y["total_lo"] or y["total"] for y in yrs])
    hi = np.array([y["total_hi"] or y["total"] for y in yrs])
    col = [SRC_COL.get(y["main_source"], MUTED) for y in yrs]
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    _style_axes(ax)
    for k, y in enumerate(yrs):
        if y["complete"]:
            ax.bar(k, v[k], color=col[k], width=0.72)
        else:  # partial fire year (first year of MODIS, running season)
            ax.bar(k, v[k], color=col[k], width=0.72, alpha=0.45, hatch="////", edgecolor="white")
    ax.errorbar(x, v, yerr=[v - lo, hi - v], fmt="none", ecolor=INK, elinewidth=0.8, capsize=1.5)
    ax.set_xticks(x[::2]); ax.set_xticklabels([yrs[k]["label"] for k in x[::2]], rotation=45, ha="right")
    seen = []
    for s in ("VIIRS_SNPP", "TA", "N20"):
        if any(y["main_source"] in ((s,) if s != "TA" else ("TA", "T", "A")) for y in yrs):
            seen.append(plt.Rectangle((0, 0), 1, 1, color=SRC_COL[s], label=t["src"][s]))
    ax.legend(handles=seen, fontsize=6.5, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0),
              ncol=len(seen), borderaxespad=0.2)
    return _png(fig)


def _n(v, lang="fr", d=0):
    if v is None:
        return "–"
    s = f"{v:,.{d}f}"
    return s.replace(",", " ").replace(".", ",") if lang == "fr" else s


def _fmt_week(cal, fw, lang):
    return cal["week_labels"][fw] if fw is not None else "–"


RISK_TXT = {"fr": {"high": ("#d03b3b", "▲▲ risque élevé"), "moderate": ("#b77d00", "▲ risque modéré"),
                   "low": ("#0a8a0a", "● normal ou inférieur"), "offseason": ("#898781", "· activité faible")},
            "en": {"high": ("#d03b3b", "▲▲ high risk"), "moderate": ("#b77d00", "▲ moderate risk"),
                   "low": ("#0a8a0a", "● normal or below"), "offseason": ("#898781", "· low activity")}}


def _forecast_box(fc: dict, lang: str, P) -> Table:
    fr = lang == "fr"
    rows = [[Paragraph(f"<b>{'Prévision IA — 2 et 4 prochaines semaines' if fr else 'AI forecast — next 2 and 4 weeks'}</b>", P), ""]]
    for key, lab in (("next2", "2 semaines" if fr else "2 weeks"), ("next4", "4 semaines" if fr else "4 weeks")):
        b = fc[key]
        col, txt = RISK_TXT[lang][b["risk"]]
        pa = f" · P(&gt; p75) {_n(100 * b['prob_above'], lang)} %" if b.get("prob_above") is not None else ""
        rows.append([Paragraph(f"{lab} : <font color='{col}'><b>{_g(txt)}</b></font> — ~{_n(b['mu'], lang)} "
                               f"({_n(b['lo'], lang)}–{_n(b['hi'], lang)}) · ×{_n(b['ratio'], lang, 2)} "
                               f"{'la normale' if fr else 'normal'}{pa}", P), ""])
    rows.append([Paragraph(f"<i>{fc['message']}</i>", P), ""])
    tb = Table(rows, colWidths=[150 * mm, 28 * mm])
    tb.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#e8692a")),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4ea")),
                            *[("SPAN", (0, i), (1, i)) for i in range(len(rows))]]))
    return tb


def _header_logos(partners: list[dict] | None):
    """Partner logos for the dark header band, each on its own tile (night blue for light logos, white otherwise)."""
    cells, styles, widths = [], [], []
    for p in (partners or [])[:2]:
        logo = str(p.get("logo") or "")
        if not logo.startswith("/assets/"):
            continue
        path = (config.WEB / logo.lstrip("/")).resolve()
        if config.WEB.resolve() not in path.parents or not path.exists():
            continue
        try:
            from reportlab.lib.utils import ImageReader
            w, h = ImageReader(str(path)).getSize()
        except Exception:
            continue
        hh = 9 * mm if w / h > 1.6 else 13 * mm  # square logos (e.g. SENSAT) need more height to stay legible
        img = Image(str(path), width=min(hh * w / h, 24 * mm), height=min(hh, 24 * mm * h / w), mask="auto")
        if cells:  # gap between tiles
            cells.append("")
            widths.append(3 * mm)
        cells.append(img)
        widths.append(img.drawWidth + 5 * mm)
        i = len(cells) - 1  # light logos on a night-blue tile (their red accents vanish on the red band)
        styles.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor("#161821") if p.get("dark") else colors.white))
    if not cells:
        return None
    tb = Table([cells], colWidths=widths)
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
                            *styles]))
    return tb


def build(zone_name: str, cal: dict, lang: str = "fr", validation: dict | None = None,
          last_date: str | None = None, forecast: dict | None = None, partners: list[dict] | None = None) -> bytes:
    t = T.get(lang, T["fr"])
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"FireSync Sahel — {t['title']} — {zone_name}", author="FireSync Sahel")
    ss = getSampleStyleSheet()
    H = ParagraphStyle("h", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
                       textColor=colors.HexColor(INK), spaceBefore=8, spaceAfter=4)
    P = ParagraphStyle("p", parent=ss["Normal"], fontName="Helvetica", fontSize=8.6, leading=11.5,
                       textColor=colors.HexColor(INK2))
    S = ParagraphStyle("s", parent=P, fontSize=7.2, leading=9.5, textColor=colors.HexColor(MUTED))
    story = []

    # header band: title | partner logos | zone
    logos = _header_logos(partners)
    title = Paragraph(f"<font color='#ffffff' size=15><b>FireSync Sahel</b></font><br/>"
                      f"<font color='#ffe2c4' size=10>{t['title']}</font>", P)
    info = Paragraph(f"<font color='#ffffff' size=9><b>{zone_name}</b><br/>"
                     f"{t['generated']} {date.today().isoformat()}"
                     f"{'<br/>' + t['data_to'] + ' ' + last_date if last_date else ''}</font>", P)
    head = (Table([[title, logos, info]], colWidths=[60 * mm, 66 * mm, 52 * mm]) if logos
            else Table([[title, info]], colWidths=[100 * mm, 78 * mm]))
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#7a2412")),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [head, Spacer(1, 6)]
    story.append(Paragraph(f"{t['area']} : {_n(cal.get('area_km2'), lang)} km² · {t['unit']}", S))

    # current season box
    cur = cal.get("current")
    if cur and cur.get("last_status"):
        ls = cur["last_status"]
        col, icon = STATUS.get(ls["status"], STATUS["nodata"])
        cs = cur.get("cumulative_status", "nodata")
        ccol, cicon = STATUS.get(cs, STATUS["nodata"])
        box = Table([[Paragraph(f"<b>{t['current']} {cur['label']}</b>", P), ""],
                     [Paragraph(f"{t['lastweek']} ({_fmt_week(cal, ls['fweek'], lang)}) : "
                                f"<font color='{col}'><b>{_g(icon)} {t['status'][ls['status']]}</b></font> "
                                f"— {_n(ls['value'], lang)} ({t['pct']} {_n(ls['pct'], lang)})", P), ""],
                     [Paragraph(f"{t['cum']} : <b>{_n(cur['cumulative'], lang)}</b> — "
                                f"<font color='{ccol}'><b>{_g(cicon)} {t['status'][cs]}</b></font>", P), ""]],
                    colWidths=[150 * mm, 28 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c3c2b7")),
                                 ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf7f1")),
                                 ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 1), (1, 1)), ("SPAN", (0, 2), (1, 2))]))
        story += [Spacer(1, 6), box]
    if forecast:
        story += [Spacer(1, 6), _forecast_box(forecast, lang, P)]

    # key indicators
    s, cr, tr = cal["summary"], cal["critical"], cal["trends"]
    def trend_txt(k, unit):
        x = tr.get(k)
        if not x:
            return "–"
        val = x.get("pct_per_decade") if k == "total" else x["slope"]
        sig = t["signif"] if x["significant"] else t["nonsignif"]
        return f"{val:+.1f} {unit} {t['per_decade']} ({sig}, p={x['p']:.2f})"
    rows = [[t["onset"], _fmt_week(cal, s.get("onset"), lang)],
            [t["peak"], _fmt_week(cal, s.get("peak"), lang)],
            [t["end"], _fmt_week(cal, s.get("end"), lang)],
            [t["duration"], f"{s.get('duration') or '–'} {t['weeks']}"]]
    for k, lab in (("50", t["crit50"]), ("80", t["crit80"])):
        c = cr.get(k)
        if c:
            rows.append([lab, f"{_fmt_week(cal, c['start'], lang)} → {_fmt_week(cal, c['end'], lang)} "
                              f"({c['weeks']} {t['weeks']})"])
    rows.append([t["trend_total"], trend_txt("total", "%")])
    rows.append([t["trend_onset"], trend_txt("onset", t["weeks"])])
    kt = Table([[Paragraph(a, P), Paragraph(f"<b>{_g(b)}</b>", P)] for a, b in rows], colWidths=[70 * mm, 108 * mm])
    kt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor(GRID)),
                            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [Paragraph(t["key"], H), kt]

    story += [KeepTogether([Paragraph(t["calendar"], H), Image(heatmap_png(cal, t), width=178 * mm,
                                                               height=178 * mm * (0.17 * len(cal["years"]) + 0.9) / 7.4)])]
    story += [KeepTogether([Paragraph(t["clim"], H), Image(clim_png(cal, t), width=178 * mm, height=60 * mm)])]
    story += [KeepTogether([Paragraph(t["annual"], H), Image(annual_png(cal, t), width=178 * mm, height=62 * mm)])]

    an = [y for y in cal["anomalies"]["years"] if y["flags"]]
    if an:
        lab = {"high": t["high"], "low": t["low"], "early": t["early"], "late": t["late"]}
        lbl = {y["fyear"]: y["label"] for y in cal["years"]}
        rows = [[lbl.get(a["fyear"], a["fyear"]), ", ".join(lab[f] for f in a["flags"]),
                 _n(a["total"], lang), _n(a["pct"], lang)] for a in an]
        at = Table([["", "", "Total", "pct"]] + rows, colWidths=[25 * mm, 90 * mm, 33 * mm, 30 * mm])
        at.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(INK2)),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(GRID))]))
        story += [KeepTogether([Paragraph(t["anoms"], H), at])]

    story += [Paragraph(t["method"], H), Paragraph(_g(t["method_txt"]), P), Spacer(1, 3),
              Paragraph(t["limits"], P)]
    if validation:
        story += [Spacer(1, 3), Paragraph(f"<b>{t['validation']}</b> : {validation}", P)]
    story += [Spacer(1, 6), Paragraph(config.FIRMS_ACK.get(lang, config.FIRMS_ACK["en"]), S),
              Paragraph("Données : NASA FIRMS / LANCE (MODIS C6.1, VIIRS 375 m S-NPP, NOAA-20, NOAA-21), NASA LP DAAC "
                        "(MCD12Q1, MCD64A1) via Earthdata et Microsoft Planetary Computer ; limites administratives "
                        "geoBoundaries. Projet développé dans le cadre du NASA Space Apps Challenge (Dakar) ; "
                        "FireSync Sahel n'est pas un produit officiel de la NASA." if lang == "fr" else
                        "Data: NASA FIRMS / LANCE (MODIS C6.1, VIIRS 375 m S-NPP, NOAA-20, NOAA-21), NASA LP DAAC "
                        "(MCD12Q1, MCD64A1) via Earthdata and Microsoft Planetary Computer; administrative boundaries "
                        "geoBoundaries. Project built for the NASA Space Apps Challenge (Dakar); FireSync Sahel is not "
                        "an official NASA product.", S)]
    doc.build(story)
    return buf.getvalue()
