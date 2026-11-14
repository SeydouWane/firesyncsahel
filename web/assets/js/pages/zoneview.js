// Zone results dashboard (shared by the public explorer and the pro analysis).
import { t, getLang } from "../i18n.js";
import { esc, fmt, fmtInt, fmtSigned, statusChip, STATUS, icons, $, toast, copyText } from "../ui.js";
import * as charts from "../charts.js";
import { api } from "../api.js";

async function loadForecast(container, geometry, name) {
  const box = $("#fc-zone", container);
  if (!box || !geometry) return;
  try {
    const z = await api.post("/api/zone/forecast", { geometry, name, lang: getLang() });
    if (!box.isConnected) return;
    const { blockHtml } = await import("./forecast.js");
    box.innerHTML = `<div class="card"><div class="card-head"><h3>${icons.spark} ${esc(t("fc.zone_t"))}</h3>
        <span class="hint">${esc(t("fc.issued"))} ${esc(z.issue.week_end)}</span>
        <div class="tools"><a class="btn sm ghost" href="#/forecast">${esc(t("nav.forecast"))} →</a></div></div>
      <div class="card-body"><div class="grid g2">
        <div class="stack" style="gap:10px">${blockHtml(z.next2, t("fc.next2"))}${blockHtml(z.next4, t("fc.next4"))}
          <div><div class="sms">${esc(z.message)}</div><div class="row" style="justify-content:space-between;margin-top:6px">
            <span class="sms-meta">${esc(t("fc.sms_h"))}</span><button class="btn sm" id="fc-copy">${icons.copy}${esc(t("fc.copy"))}</button></div></div></div>
        <div><div class="small strong muted">${esc(t("fc.chart_t"))}</div><div class="chart" id="c-fcz"></div><div id="l-fcz"></div></div>
      </div></div></div>`;
    $("#fc-copy", box).addEventListener("click", async () => { if (await copyText(z.message)) toast(t("fc.copied")); });
    const draw = () => { if ($("#c-fcz", box)) $("#l-fcz", box).innerHTML = charts.forecastChart($("#c-fcz", box), z); };
    draw();
    box._redraw = draw;
  } catch (e) {
    if (box.isConnected) box.innerHTML = "";
  }
}

export function kpis(cal) {
  const L = cal.week_labels, s = cal.summary, tr = cal.trends || {};
  const wk = (i) => (i == null ? "–" : esc(L[i]));
  const trTotal = tr.total;
  const trOnset = tr.onset;
  const sig = (x) => (x ? (x.significant ? t("common.significant") : t("common.not_significant")) : "");
  const cur = cal.current;
  const ls = cur?.last_status;
  return `<div class="kpis">
    <div class="kpi"><div class="label">${esc(t("ex.onset"))}</div><div class="value">${wk(s.onset)}</div>
      <div class="note">${trOnset ? `${fmtSigned(trOnset.slope, 1)} ${esc(t("common.weeks"))} ${esc(t("common.per_decade"))} · ${esc(sig(trOnset))}` : "&nbsp;"}</div></div>
    <div class="kpi"><div class="label">${esc(t("ex.peak"))}</div><div class="value">${wk(s.peak)}</div><div class="note">&nbsp;</div></div>
    <div class="kpi"><div class="label">${esc(t("ex.end"))}</div><div class="value">${wk(s.end)}</div><div class="note">&nbsp;</div></div>
    <div class="kpi"><div class="label">${esc(t("ex.duration"))}</div><div class="value">${s.duration ?? "–"}<small>${esc(t("common.weeks"))}</small></div><div class="note">&nbsp;</div></div>
    <div class="kpi"><div class="label">${esc(t("ex.trend"))}</div>
      <div class="value">${trTotal ? fmtSigned(trTotal.pct_per_decade, 0, " %") : "–"}</div>
      <div class="note">${trTotal ? `${esc(t("common.per_decade"))} · ${esc(sig(trTotal))}` : "&nbsp;"}</div></div>
    <div class="kpi hl"><div class="label">${esc(t("ex.current"))} ${cur ? esc(cur.label) : ""}</div>
      <div class="value" style="font-size:16px;margin-top:8px">${cur ? statusChip(cur.cumulative_status) : "–"}</div>
      <div class="note">${cur ? `${esc(t("ex.cum"))} : ${fmtInt(cur.cumulative)}` : "&nbsp;"}</div></div>
  </div>`;
}

export function statusBanner(cal) {
  const cur = cal.current;
  if (!cur || !cur.last_status) return "";
  const ls = cur.last_status;
  const st = STATUS[ls.status] || STATUS.nodata;
  const cls = st.cls === "crit" ? "crit" : st.cls === "warn" ? "warn" : st.cls === "ok" ? "ok" : "";
  const bg = st.cls === "crit" ? "var(--crit)" : st.cls === "warn" ? "#b77d00" : st.cls === "ok" ? "var(--ok)" : "var(--muted)";
  return `<div class="status-banner ${cls}">
    <div class="status-icon" style="background:${bg}" aria-hidden="true">${st.icon}</div>
    <div><div class="small muted strong">${esc(t("ex.current"))} ${esc(cur.label)} · ${esc(t("ex.last_week"))} ${esc(cal.week_labels[ls.fweek])}</div>
      <div class="big">${esc(t("status." + ls.status))}</div>
      <div class="small ink2">${fmtInt(ls.value)} ${esc(t("common.unit_short"))} · ${esc(t("ex.pct"))} ${fmt(ls.pct, 0)} ${esc(t("ex.vs_hist"))}
        · ${esc(t("ex.cum"))} ${fmtInt(cur.cumulative)} (${esc(t("ex.pct"))} ${fmt(cur.cumulative_pct, 0)})</div></div>
  </div>`;
}

function criticalHtml(cal) {
  const L = cal.week_labels;
  const c50 = cal.critical?.["50"], c80 = cal.critical?.["80"];
  const row = (lab, c) => c ? `<div class="row" style="justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--line)">
      <span class="ink2">${esc(lab)}</span><b>${esc(L[c.start])} → ${esc(L[c.end])}</b><span class="chip brand">${c.weeks} ${esc(t("common.weeks"))}</span></div>` : "";
  return row(t("ex.crit50"), c50) + row(t("ex.crit80"), c80);
}

function anomaliesHtml(cal) {
  const lbl = Object.fromEntries(cal.years.map((y) => [y.fyear, y.label]));
  const flagTxt = { high: t("ex.high"), low: t("ex.low"), early: t("ex.early"), late: t("ex.late") };
  const flagCls = { high: "crit", low: "low", early: "warn", late: "low" };
  const yrs = cal.anomalies.years.filter((a) => a.flags.length);
  const weeks = cal.anomalies.weeks.slice(0, 8);
  return `<div class="grid g2">
    <div><div class="small strong muted" style="margin-bottom:6px">${esc(t("ex.anom_years"))}</div>
      ${yrs.length ? yrs.map((a) => `<div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)"><b style="min-width:64px">${esc(lbl[a.fyear])}</b>
        ${a.flags.map((f) => `<span class="chip ${flagCls[f]}">${esc(flagTxt[f])}</span>`).join("")}
        <span class="muted small" style="margin-left:auto">${esc(t("ex.pct"))} ${fmt(a.pct, 0)}</span></div>`).join("") : `<p class="muted small">–</p>`}</div>
    <div><div class="small strong muted" style="margin-bottom:6px">${esc(t("ex.anom_weeks"))}</div>
      ${weeks.length ? `<div class="table-wrap"><table class="table"><tbody>${weeks.map((w) => `<tr><td>${esc(lbl[w.fyear])}</td><td>${esc(cal.week_labels[w.fweek])}</td>
        <td class="num">${fmtInt(w.value)}</td><td class="num">×${fmt(w.ratio, 1)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted small">–</p>`}</div>
  </div>`;
}

export function renderZone(container, res, { mode = "harmonized", onMode, onStart, extraActions = "", startWeek = "auto", geometry = null } = {}) {
  const cal = res.calendar;
  const months = getLang() === "fr" ? ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]
    : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthWeek = (m) => Math.min(51, Math.floor((new Date(2001, m, 1) - new Date(2001, 0, 1)) / 864e5 / 7));
  container.innerHTML = `
    <div class="results-head">
      <div><div class="eyebrow">${esc(t("ex.area"))} ${fmtInt(cal.area_km2)} km²</div><h2>${esc(res.name)}</h2></div>
      <div class="row" style="margin-left:auto">
        <div class="seg" role="group" aria-label="${esc(t("ex.mode"))}">
          <button data-mode="harmonized" aria-pressed="${mode === "harmonized"}">${esc(t("ex.mode_h"))}</button>
          <button data-mode="naive" aria-pressed="${mode === "naive"}">${esc(t("ex.mode_n"))}</button></div>
        <label class="small muted" for="start-week">${esc(t("ex.start"))}</label>
        <select class="input" id="start-week" style="width:auto;min-height:34px;padding:4px 8px">
          <option value="auto">${esc(t("ex.auto"))} (${esc(cal.week_labels[0])})</option>
          ${months.map((m, i) => `<option value="${monthWeek(i)}" ${String(startWeek) === String(monthWeek(i)) ? "selected" : ""}>1 ${esc(m)}</option>`).join("")}
        </select>
        ${extraActions}
      </div>
    </div>
    ${statusBanner(cal)}
    <div style="height:14px"></div>
    ${kpis(cal)}
    <div id="fc-zone" style="margin-top:16px"></div>
    <div class="grid" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>${esc(t("ex.heat_t"))}</h3><span class="hint">${esc(t("ex.heat_h"))}</span>
        <div class="tools" id="heat-legend"></div></div>
        <div class="card-body"><div class="chart" id="c-heat"></div>${charts.sourceLegend()}</div></div>
      <div class="grid g2">
        <div class="card"><div class="card-head"><h3>${esc(t("ex.clim_t"))}</h3><span class="hint">${esc(t("ex.clim_h"))}</span></div>
          <div class="card-body">
            ${charts.legendHtml([{ label: t("ex.median"), color: "var(--ink-2)" }, { label: t("ex.band50"), color: "var(--band-inner)" },
              { label: t("ex.band80"), color: "var(--band-outer)" }, ...(cal.current ? [{ label: `${t("ex.current")} ${cal.current.label}`, color: "var(--src-viirs)" }] : []),
              ...(cal.critical?.["50"] ? [{ label: t("ex.crit50"), color: "var(--brand-soft)" }] : [])])}
            <div class="chart" id="c-clim"></div></div></div>
        <div class="card"><div class="card-head"><h3>${esc(t("ex.annual_t"))}</h3><span class="hint">${esc(t("ex.annual_h"))}</span>
          <div class="tools"><div class="seg"><button data-view="chart" aria-pressed="true">${esc(t("common.chart"))}</button><button data-view="table" aria-pressed="false">${esc(t("common.table"))}</button></div></div></div>
          <div class="card-body"><div id="annual-chart"><div class="chart" id="c-annual"></div>${charts.sourceLegend()}</div>
            <div id="annual-table" hidden>${charts.annualTable(cal)}</div></div></div>
      </div>
      <div class="grid g2">
        <div class="card"><div class="card-head"><h3>${esc(t("ex.pheno_t"))}</h3><span class="hint">${esc(t("ex.pheno_h"))}</span></div>
          <div class="card-body"><div class="chart" id="c-pheno"></div></div></div>
        <div class="stack">
          <div class="card"><div class="card-head"><h3>${esc(t("ex.crit_t"))}</h3></div><div class="card-body">${criticalHtml(cal)}</div></div>
          <div class="card"><div class="card-head"><h3>${esc(t("ex.anom_t"))}</h3></div><div class="card-body">${anomaliesHtml(cal)}</div></div>
        </div>
      </div>
    </div>`;
  const draw = () => {
    if (!container.isConnected || !$("#c-heat", container)) return;
    const info = charts.heatmap($("#c-heat", container), cal);
    $("#heat-legend", container).innerHTML = charts.heatLegend(info.vmax);
    charts.climatology($("#c-clim", container), cal);
    charts.annual($("#c-annual", container), cal);
    charts.phenology($("#c-pheno", container), cal);
  };
  draw();
  if (mode === "harmonized") loadForecast(container, geometry, res.name);
  container.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => onMode && onMode(b.dataset.mode)));
  $("#start-week", container).addEventListener("change", (e) => onStart && onStart(e.target.value));
  container.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    container.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#annual-chart", container).hidden = b.dataset.view !== "chart";
    $("#annual-table", container).hidden = b.dataset.view !== "table";
  }));
  const onResize = () => { draw(); $("#fc-zone", container)?._redraw?.(); };
  window.addEventListener("fs-resize", onResize);
  return () => window.removeEventListener("fs-resize", onResize);
}

export function sensorsChart(el, res) {
  const a = res.sensors.annual;
  const series = [
    { key: "modis", label: "MODIS Terra + Aqua", short: "MODIS", color: "var(--src-modis)", values: a.map((r) => ({ x: r.year, y: r.MODIS_T + r.MODIS_A || null })) },
    { key: "viirs", label: "VIIRS S-NPP", short: "S-NPP", color: "var(--src-viirs)", values: a.map((r) => ({ x: r.year, y: r.VIIRS_SNPP || null })) },
    { key: "n20", label: "VIIRS NOAA-20", short: "NOAA-20", color: "var(--src-n20)", values: a.map((r) => ({ x: r.year, y: r.VIIRS_N20 || null })) },
    { key: "h", label: t("home.harm"), short: "FireSync", color: "var(--brand)", values: a.map((r) => ({ x: r.year, y: r.harmonized })) },
  ].map((s) => ({ ...s, color: getComputedStyle(document.documentElement).getPropertyValue(s.color.slice(4, -1)).trim() }));
  charts.lines(el, series, { height: 260 });
  return charts.legendHtml(series);
}
