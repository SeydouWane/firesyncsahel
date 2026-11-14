// Charts (Observable Plot). Colours are resolved from CSS tokens at render time
// so light/dark themes both get their own validated steps.
import { t, getLang } from "./i18n.js";
import { cssVar, fmt, fmtInt, esc, PCT, COLON } from "./ui.js";

const C = () => ({
  ink: cssVar("--ink"), ink2: cssVar("--ink-2"), muted: cssVar("--muted"), grid: cssVar("--chart-grid"),
  axis: cssVar("--chart-axis"), surface: cssVar("--surface"), line: cssVar("--line"),
  outer: cssVar("--band-outer"), inner: cssVar("--band-inner"), brand: cssVar("--brand"), brandSoft: cssVar("--brand-soft"),
  viirs: cssVar("--src-viirs"), modis: cssVar("--src-modis"), n20: cssVar("--src-n20"),
  heat: [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--heat-${i}`)),
  cat: [cssVar("--src-viirs"), cssVar("--src-modis"), cssVar("--src-n20"), "#eda100"],
});
const srcCol = (c, s) => (s === "VIIRS_SNPP" ? c.viirs : s === "N20" || s === "N21" ? c.n20 : s ? c.modis : c.muted);
const W = (el) => (el ? Math.max(280, Math.floor(el.getBoundingClientRect().width || el.parentElement?.clientWidth || 640)) : 640);

function base(c, extra = {}) {
  return {
    style: { background: "transparent", color: c.ink2, fontSize: "11.5px", fontFamily: "inherit", overflow: "visible" },
    ...extra,
  };
}
const tipStyle = (c) => ({ fill: c.surface, stroke: c.line, textPadding: 8, fontSize: 12 });
// el can be gone when an async response lands after navigating away
function mount(el, svg) { if (el && el.isConnected) el.replaceChildren(svg); return svg; }

// ------------------------------------------------------------- heatmap
export function heatmap(el, cal) {
  const c = C();
  const labels = cal.week_labels;
  const data = [];
  const srcRows = [];
  for (const y of cal.years) {
    y.weeks.forEach((v, i) => {
      if (v == null) return;
      data.push({ y: y.label, x: i, v, lo: y.lo[i], hi: y.hi[i], s: y.source[i], cur: y.current });
    });
    srcRows.push({ y: y.label, x: -1, s: y.main_source, complete: y.complete, cur: y.current });
  }
  const vals = data.map((d) => d.v).filter((v) => v > 0).sort((a, b) => a - b);
  const vmax = vals.length ? vals[Math.floor(vals.length * 0.995)] || vals[vals.length - 1] : 1;
  const width = W(el);
  const rowH = width < 520 ? 13 : 16;
  const years = cal.years.map((y) => y.label);
  const fmtTip = (d) => `${d.y} · ${labels[d.x]}\n${fmt(d.v, 1)} ${t("common.unit_short")}` +
    (d.hi > d.lo ? `\n90 % : ${fmt(d.lo, 0)} – ${fmt(d.hi, 0)}` : "") + `\n${t("src." + (d.s || "modis"))}`;
  const plot = Plot.plot(base(c, {
    width, height: years.length * rowH + 46, marginLeft: 64, marginRight: 8, marginTop: 6, marginBottom: 34,
    x: { type: "band", domain: [-1, ...d3.range(52)], padding: 0.06, label: null,
         tickFormat: (i) => (i < 0 ? "" : i % (width < 520 ? 8 : 4) === 0 ? labels[i] : ""), tickSize: 0 },
    y: { type: "band", domain: years, padding: 0.08, label: null, tickSize: 0 },
    // below 1 detection / week everything shares the lightest step: modelled
    // years carry an expectation (e.g. 0.6), observed years an integer (0)
    color: { type: "log", domain: [1, Math.max(vmax, 2)], interpolate: d3.interpolateRgbBasis(c.heat), clamp: true },
    marks: [
      Plot.cell(srcRows, { x: "x", y: "y", fill: (d) => srcCol(c, d.s), inset: 1, rx: 2, fillOpacity: (d) => (d.complete ? 1 : 0.45) }),
      Plot.cell(data, { x: "x", y: "y", fill: (d) => Math.max(d.v, 1), inset: 0.5, rx: 2 }),
      Plot.tip(data, Plot.pointer({ x: "x", y: "y", title: fmtTip, ...tipStyle(c) })),
    ],
  }));
  mount(el, plot);
  return { vmax };
}

export function heatLegend(vmax) {
  return `<div class="heat-legend"><span>0</span><span class="bar"></span><span>${fmtInt(vmax)}+ ${esc(t("common.unit_short"))} / ${esc(t("common.week"))}</span></div>`;
}
export function sourceLegend(sources = ["VIIRS_SNPP", "TA", "N20"]) {
  const c = C();
  return `<div class="legend">${sources.map((s) => `<span><i class="sw" style="background:${srcCol(c, s)}"></i>${esc(t("src." + s))}</span>`).join("")}</div>`;
}

// ------------------------------------------------------------- climatology
export function climatology(el, cal) {
  const c = C();
  const cl = cal.climatology;
  const labels = cal.week_labels;
  const rows = d3.range(52).map((i) => ({ x: i, p10: cl.p10?.[i], p25: cl.p25?.[i], p50: cl.p50?.[i], p75: cl.p75?.[i], p90: cl.p90?.[i] }));
  const cur = cal.current?.weeks?.map((w) => ({ x: w.fweek, v: w.value, s: w.status, pct: w.pct })) || [];
  const crit = cal.critical?.["50"];
  const width = W(el);
  const marks = [];
  if (crit) marks.push(Plot.rectY([crit], { x1: (d) => d.start - 0.5, x2: (d) => d.end + 0.5, y1: 0, y2: d3.max(rows, (r) => r.p90) || 1, fill: c.brandSoft, fillOpacity: 0.7 }));
  marks.push(
    Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
    Plot.areaY(rows, { x: "x", y1: "p10", y2: "p90", fill: c.outer, curve: "monotone-x" }),
    Plot.areaY(rows, { x: "x", y1: "p25", y2: "p75", fill: c.inner, curve: "monotone-x" }),
    Plot.lineY(rows, { x: "x", y: "p50", stroke: c.ink2, strokeWidth: 2, curve: "monotone-x" }),
    Plot.ruleY([0], { stroke: c.axis }),
  );
  if (cur.length) {
    marks.push(Plot.lineY(cur, { x: "x", y: "v", stroke: c.viirs, strokeWidth: 2.2, curve: "monotone-x" }));
    marks.push(Plot.dot(cur.slice(-1), { x: "x", y: "v", r: 4.5, fill: c.viirs, stroke: c.surface, strokeWidth: 2 }));
    marks.push(Plot.text(cur.slice(-1), { x: "x", y: "v", text: () => cal.current.label, dx: 8, textAnchor: "start", fill: c.ink, fontWeight: 700 }));
  }
  marks.push(Plot.tip(rows, Plot.pointerX({
    x: "x", y: "p50", ...tipStyle(c),
    title: (d) => {
      const cv = cur.find((q) => q.x === d.x);
      return `${labels[d.x]}\n${t("ex.median")}${COLON()} ${fmt(d.p50, 0)}\n${t("ex.band50")}${COLON()} ${fmt(d.p25, 0)} – ${fmt(d.p75, 0)}\n${t("ex.band80")}${COLON()} ${fmt(d.p10, 0)} – ${fmt(d.p90, 0)}` +
        (cv ? `\n${cal.current.label}${COLON()} ${fmt(cv.v, 0)} (${t("ex.pct")} ${fmt(cv.pct, 0)})` : "");
    },
  })));
  mount(el, Plot.plot(base(c, {
    width, height: 260, marginLeft: 46, marginRight: 70, marginBottom: 30,
    x: { domain: [0, 51], ticks: d3.range(0, 52, width < 520 ? 8 : 4), tickFormat: (i) => labels[i], label: null, tickSize: 0 },
    y: { label: null, nice: true, tickFormat: (v) => fmtInt(v), tickSize: 0 },
    marks,
  })));
}

// ------------------------------------------------------------- annual totals
export function annual(el, cal) {
  const c = C();
  const rows = cal.years.filter((y) => y.total != null).map((y) => ({ ...y }));
  const width = W(el);
  const every = width < 560 ? 4 : 2;
  mount(el, Plot.plot(base(c, {
    width, height: 250, marginLeft: 52, marginBottom: 44,
    x: { type: "band", domain: rows.map((r) => r.label), padding: 0.22, label: null, tickSize: 0,
         tickFormat: (d, i) => (i % every === 0 ? d : ""), tickRotate: width < 560 ? -45 : 0 },
    y: { label: null, nice: true, tickFormat: (v) => fmtInt(v), tickSize: 0 },
    marks: [
      Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
      Plot.barY(rows, { x: "label", y: "total", fill: (d) => srcCol(c, d.main_source), fillOpacity: (d) => (d.complete ? 1 : 0.4), rx: 3 }),
      Plot.ruleX(rows, { x: "label", y1: "total_lo", y2: "total_hi", stroke: c.ink, strokeWidth: 1.2 }),
      Plot.ruleY([0], { stroke: c.axis }),
      Plot.tip(rows, Plot.pointerX({ x: "label", y: "total", ...tipStyle(c),
        title: (d) => `${d.label}${d.complete ? "" : " (" + (d.current ? t("ex.current_lbl") : t("ex.partial")) + ")"}\n${fmtInt(d.total)} ${t("common.unit_short")}` +
          (d.total_hi > d.total_lo ? `\n90 % : ${fmtInt(d.total_lo)} – ${fmtInt(d.total_hi)}` : "") + `\n${t("src." + (d.main_source || "modis"))}` })),
    ],
  })));
}

export function annualTable(cal) {
  const rows = cal.years.filter((y) => y.total != null);
  return `<div class="table-wrap"><table class="table"><thead><tr><th></th><th class="num">Total</th><th class="num">90 %</th>
    <th>${esc(t("ex.onset"))}</th><th>${esc(t("ex.peak"))}</th><th>${esc(t("ex.end"))}</th><th>Source</th></tr></thead><tbody>
    ${rows.map((y) => `<tr><td>${esc(y.label)}${y.complete ? "" : ` <span class="muted small">(${esc(y.current ? t("ex.current_lbl") : t("ex.partial"))})</span>`}</td>
      <td class="num">${fmtInt(y.total)}</td><td class="num">${y.total_hi > y.total_lo ? `${fmtInt(y.total_lo)} – ${fmtInt(y.total_hi)}` : "–"}</td>
      <td>${y.onset != null ? esc(cal.week_labels[y.onset]) : "–"}</td><td>${y.peak != null ? esc(cal.week_labels[y.peak]) : "–"}</td>
      <td>${y.end != null ? esc(cal.week_labels[y.end]) : "–"}</td><td class="small">${esc(t("src." + (y.main_source || "modis")))}</td></tr>`).join("")}
    </tbody></table></div>`;
}

// ------------------------------------------------------------- phenology
export function phenology(el, cal) {
  const c = C();
  const labels = cal.week_labels;
  const rows = cal.years.filter((y) => y.complete && y.onset != null);
  const width = W(el);
  const s = cal.summary;
  mount(el, Plot.plot(base(c, {
    width, height: rows.length * 15 + 44, marginLeft: 64, marginBottom: 30,
    x: { domain: [0, 51], ticks: d3.range(0, 52, width < 520 ? 8 : 4), tickFormat: (i) => labels[i], label: null, tickSize: 0 },
    y: { type: "band", domain: rows.map((r) => r.label), padding: 0.35, label: null, tickSize: 0 },
    marks: [
      Plot.gridX({ stroke: c.grid, strokeOpacity: 1, ticks: d3.range(0, 52, 4) }),
      s.onset != null ? Plot.ruleX([s.onset, s.end], { stroke: c.muted, strokeWidth: 1 }) : null,
      Plot.barX(rows, { y: "label", x1: (d) => d.onset, x2: (d) => d.end + 1, fill: c.modis, fillOpacity: 0.55, rx: 3 }),
      Plot.dot(rows, { y: "label", x: (d) => d.peak + 0.5, r: 4, fill: c.brand, stroke: c.surface, strokeWidth: 1.5 }),
      Plot.tip(rows, Plot.pointerY({ y: "label", x: (d) => d.peak + 0.5, ...tipStyle(c),
        title: (d) => `${d.label}\n${t("ex.onset")}${COLON()} ${labels[d.onset]}\n${t("ex.peak")}${COLON()} ${labels[d.peak]}\n${t("ex.end")}${COLON()} ${labels[d.end]}\n${t("ex.duration")}${COLON()} ${d.duration} ${t("common.weeks")}` })),
    ].filter(Boolean),
  })));
}

// ------------------------------------------------------------- comparison lines
export function lines(el, series, { height = 260, yFormat = fmtInt, xLabel = null, interval = null, endLabels = true } = {}) {
  // series: [{key, label, color, values:[{x, y}]}]
  const c = C();
  const width = W(el);
  const flat = series.flatMap((s) => s.values.filter((v) => v.y != null).map((v) => ({ ...v, key: s.key, label: s.label, color: s.color })));
  const marks = [Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }), Plot.ruleY([0], { stroke: c.axis })];
  if (interval) marks.push(Plot.areaY(interval.values, { x: "x", y1: "lo", y2: "hi", fill: interval.color, fillOpacity: 0.18 }));
  // end labels: spread vertically when two series end at nearly the same value
  const ends = series.map((s) => { const v = s.values.filter((q) => q.y != null); return { s, last: v[v.length - 1] }; }).filter((e) => e.last);
  const ys = flat.map((d) => d.y), span = (Math.max(...ys, 0) - Math.min(...ys, 0)) || 1;
  ends.sort((a, b) => b.last.y - a.last.y);
  const plotH = height - 50;
  let prevPx = -Infinity;
  ends.forEach((e) => {
    const px = (1 - e.last.y / span) * plotH;
    e.dy = px - prevPx < 14 ? prevPx + 14 - px : 0;
    prevPx = px + e.dy;
  });
  for (const s of series) {
    const vals = s.values.filter((v) => v.y != null);
    marks.push(Plot.lineY(vals, { x: "x", y: "y", stroke: s.color, strokeWidth: 2.2 }));
    const e = ends.find((q) => q.s === s);
    if (endLabels && e) marks.push(Plot.text([e.last], { x: "x", y: "y", text: () => s.short || s.label, dx: 6, dy: e.dy, textAnchor: "start", fill: c.ink2, fontWeight: 650 }));
  }
  marks.push(Plot.tip(flat, Plot.pointer({ x: "x", y: "y", ...tipStyle(c), title: (d) => `${d.x}\n${d.label}${COLON()} ${yFormat(d.y)}` })));
  mount(el, Plot.plot(base(c, {
    width, height, marginLeft: 54, marginRight: endLabels ? 96 : 16, marginBottom: 30,
    x: { label: xLabel, tickFormat: (d) => String(d), tickSize: 0 },
    y: { label: null, nice: true, tickFormat: yFormat, tickSize: 0 },
    marks,
  })));
}

export function legendHtml(items) {
  return `<div class="legend">${items.map((i) => `<span><i class="ln" style="background:${i.color}"></i>${esc(i.label)}</span>`).join("")}</div>`;
}

// ------------------------------------------------------------- grouped bars (method page)
export function groupedBars(el, rows, { groups, keys, labels, yFormat = (v) => fmt(v, 0) + PCT(), height = 260 }) {
  const c = C();
  const width = W(el);
  const flat = rows.flatMap((r) => keys.map((k, i) => ({ g: r.g, k, v: r[k], color: c.cat[i] })).filter((d) => d.v != null));
  mount(el, Plot.plot(base(c, {
    width, height, marginLeft: 48, marginBottom: 34,
    fx: { domain: groups.map((g) => g.key), tickFormat: (k) => groups.find((g) => g.key === k)?.label, label: null, padding: 0.12 },
    x: { domain: keys, axis: null, padding: 0.12 },
    y: { label: null, nice: true, tickFormat: yFormat, tickSize: 0 },
    marks: [
      Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
      Plot.barY(flat, { fx: "g", x: "k", y: "v", fill: (d) => d.color, rx: 3 }),
      Plot.ruleY([0], { stroke: c.axis }),
      Plot.tip(flat, Plot.pointer({ fx: "g", x: "k", y: "v", ...tipStyle(c), title: (d) => `${labels[d.k]}\n${yFormat(d.v)}` })),
    ],
  })));
  return `<div class="legend">${keys.map((k, i) => `<span><i class="sw" style="background:${c.cat[i]}"></i>${esc(labels[k])}</span>`).join("")}</div>`;
}

// ------------------------------------------------------------- AI forecast
export function forecastChart(el, z, lang = getLang()) {
  const c = C();
  const fmtD = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { day: "numeric", month: "short" });
  const rec = z.recent.map((r) => ({ x: fmtD(r.start), v: r.value, n: r.normal, kind: "obs" }));
  const fc = z.weeks.map((w) => ({ x: fmtD(w.start), v: w.mu, lo: w.lo, hi: w.hi, p25: w.p25, p50: w.p50, p75: w.p75, kind: "fc" }));
  const all = [...rec, ...fc];
  const width = W(el);
  mount(el, Plot.plot(base(c, {
    width, height: 230, marginLeft: 46, marginBottom: 34,
    x: { type: "band", domain: all.map((d) => d.x), padding: 0.25, label: null, tickSize: 0, tickRotate: width < 520 ? -40 : 0 },
    y: { label: null, nice: true, tickFormat: fmtInt, tickSize: 0 },
    marks: [
      Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
      Plot.barY(fc, { x: "x", y1: "p25", y2: "p75", fill: c.outer, fillOpacity: 0.9, insetLeft: -6, insetRight: -6 }),
      Plot.barY(rec, { x: "x", y: "v", fill: c.viirs, rx: 3 }),
      Plot.barY(fc, { x: "x", y: "v", fill: c.brand, fillOpacity: 0.85, rx: 3 }),
      Plot.ruleX(fc, { x: "x", y1: "lo", y2: "hi", stroke: c.ink, strokeWidth: 1.4 }),
      Plot.tickY(all, { x: "x", y: (d) => (d.kind === "obs" ? d.n : d.p50), stroke: c.ink2, strokeWidth: 2 }),
      Plot.ruleY([0], { stroke: c.axis }),
      Plot.tip(all, Plot.pointerX({ x: "x", y: "v", ...tipStyle(c), title: (d) => d.kind === "obs"
        ? `${d.x} · ${t("fc.observed")}\n${fmtInt(d.v)}\n${t("fc.normal")}${COLON()} ${fmtInt(d.n)}`
        : `${d.x} · ${t("fc.predicted")}\n${fmtInt(d.v)} (${fmtInt(d.lo)} – ${fmtInt(d.hi)})\n${t("fc.normal")}${COLON()} ${fmtInt(d.p50)}` })),
    ],
  })));
  return `<div class="legend"><span><i class="sw" style="background:${c.viirs}"></i>${esc(t("fc.observed"))}</span>
    <span><i class="sw" style="background:${c.brand}"></i>${esc(t("fc.predicted"))} · ${esc(t("fc.interval"))}</span>
    <span><i class="ln" style="background:${c.ink2}"></i>${esc(t("fc.normal"))}</span>
    <span><i class="sw" style="background:${c.outer}"></i>${esc(t("fc.normal_band"))}</span></div>`;
}

// rel = calibrated probabilities, raw (optional) = before recalibration
export function reliabilityChart(el, rel, raw = null) {
  const c = C();
  const width = Math.min(W(el), 440);
  const pts = [...rel.map((d) => ({ ...d, s: "cal" })), ...(raw || []).map((d) => ({ ...d, s: "raw" }))];
  const name = { cal: t("fc.rel_cal"), raw: t("fc.rel_raw") };
  mount(el, Plot.plot(base(c, {
    width, height: 230, marginLeft: 44, marginBottom: 36,
    x: { domain: [0, 1], label: t("fc.prob_above"), tickFormat: (v) => `${Math.round(v * 100)}${PCT()}` },
    y: { domain: [0, 1], label: null, tickFormat: (v) => `${Math.round(v * 100)}${PCT()}` },
    marks: [
      Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
      Plot.line([[0, 0], [1, 1]], { stroke: c.axis, strokeWidth: 1 }),
      raw ? Plot.line(raw, { x: "p", y: "obs", stroke: c.muted, strokeWidth: 2, strokeDasharray: "4 3" }) : null,
      raw ? Plot.dot(raw, { x: "p", y: "obs", r: 3.5, fill: c.surface, stroke: c.muted, strokeWidth: 1.8 }) : null,
      Plot.line(rel, { x: "p", y: "obs", stroke: c.brand, strokeWidth: 2 }),
      Plot.dot(rel, { x: "p", y: "obs", r: (d) => 3.5 + Math.sqrt(d.n) / 12, fill: c.brand, stroke: c.surface, strokeWidth: 1.5 }),
      Plot.tip(pts, Plot.pointer({ x: "p", y: "obs", ...tipStyle(c),
        title: (d) => `${name[d.s]}\n${Math.round(d.p * 100)}${PCT()} → ${Math.round(d.obs * 100)}${PCT()}\nn = ${fmtInt(d.n)}` })),
    ],
  })));
  return `<div class="legend"><span><i class="ln" style="background:${c.brand}"></i>${esc(name.cal)}</span>
    ${raw ? `<span><i class="ln dash" style="border-color:${c.muted}"></i>${esc(name.raw)}</span>` : ""}
    <span><i class="ln" style="background:${c.axis}"></i>${esc(t("fc.rel_perfect"))}</span></div>`;
}

// ------------------------------------------------------------- sparkline (inline svg)
export function sparkline(values, { w = 140, h = 36, color } = {}) {
  const v = values.filter((x) => x != null);
  if (v.length < 2) return "";
  const max = Math.max(...v), min = Math.min(0, ...v);
  const px = (i) => (i / (v.length - 1)) * (w - 6) + 3;
  const py = (x) => h - 3 - ((x - min) / (max - min || 1)) * (h - 8);
  const d = v.map((x, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(x).toFixed(1)}`).join("");
  const col = color || "var(--brand)";
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${px(v.length - 1)}" cy="${py(v[v.length - 1])}" r="3" fill="${col}"/></svg>`;
}

// ------------------------------------------------------------- sensor bars (admin)
export function sensorYears(el, perYear) {
  const c = C();
  const col = { MODIS_T: c.modis, MODIS_A: "#eda100", VIIRS_SNPP: c.viirs, VIIRS_N20: c.n20, VIIRS_N21: "#6250d6" };
  const width = W(el);
  mount(el, Plot.plot(base(c, {
    width, height: 240, marginLeft: 54, marginBottom: 30,
    x: { label: null, tickFormat: (d) => String(d), tickSize: 0 },
    y: { label: null, nice: true, tickFormat: fmtInt, tickSize: 0 },
    marks: [
      Plot.gridY({ stroke: c.grid, strokeOpacity: 1 }),
      Plot.lineY(perYear, { x: "year", y: "n", z: "sensor", stroke: (d) => col[d.sensor] || c.muted, strokeWidth: 2 }),
      Plot.tip(perYear, Plot.pointer({ x: "year", y: "n", ...tipStyle(c), title: (d) => `${d.year} · ${d.sensor}\n${fmtInt(d.n)}` })),
    ],
    marginRight: 16,
  })));
  const present = new Set(perYear.map((d) => d.sensor));
  return legendHtml(Object.entries(col).filter(([k]) => present.has(k)).map(([k, v]) => ({ label: k.replace("_", " "), color: v })));
}
