// Prévisions IA: district-level fire forecast for the next 2-4 weeks.
import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, $$, esc, icons, fmt, fmtInt, fmtDay, toast, loadingBlock, errorBlock, riskChip, RISK, copyText, statusChip, PCT, COLON } from "../ui.js";
import * as charts from "../charts.js";
import { FireMap, isDark } from "../map.js";
import { footer } from "./data.js";
import { plainBox, howTo, forecastStory, skillStory, inPlace, inRegion } from "../explain.js";

const ORDER = { high: 0, moderate: 1, low: 2, offseason: 3 };
const state = { level: 2, horizon: "next2", sel: null, all: false };

function smsCard(msg) {
  return `<div class="card-head" style="padding:0 0 8px"><h3 style="font-size:14.5px">${icons.sms} ${esc(t("fc.sms_t"))}</h3></div>
    <div class="sms" id="sms-text">${esc(msg)}</div>
    <div class="row" style="justify-content:space-between;margin-top:8px"><span class="sms-meta">${msg.length} ${getLang() === "fr" ? "car." : "chars"} · ${esc(t("fc.sms_h"))}</span>
      <button class="btn sm" id="sms-copy">${icons.copy}${esc(t("fc.copy"))}</button></div>`;
}
export function bindCopy(root, msg) {
  $("#sms-copy", root)?.addEventListener("click", async () => { if (await copyText(msg)) toast(t("fc.copied")); });
}

export function blockHtml(b, label) {
  return `<div class="kpi"><div class="label">${esc(label)}</div>
    <div class="value">${fmtInt(b.mu)}<small>${esc(t("common.detections"))}</small></div>
    <div class="note">${esc(t("fc.interval"))} ${fmtInt(b.lo)} – ${fmtInt(b.hi)} · ${esc(t("ex.median"))} ${fmtInt(b.normal)}</div>
    <div class="row" style="margin-top:8px;gap:6px">${riskChip(b.risk)}
      <span class="chip">×${fmt(b.ratio, 1)} ${esc(t("fc.vs_normal"))}</span>
      ${b.prob_above != null ? `<span class="chip" title="${esc(t("fc.prob_tip"))}">${fmt(100 * b.prob_above, 0)}${getLang() === "fr" ? " %" : "%"} ${esc(t("fc.prob_short"))}</span>` : ""}</div></div>`;
}

// with / without MODIS NDVI fuel: same leave-one-season-out validation
function ablationHtml(v) {
  const a = v.ablation;
  if (!a || Object.keys(a).length < 2) return "";
  const pct = (x) => (x == null ? "–" : `${x >= 0 ? "+" : ""}${fmt(100 * x, 1)}${PCT()}`);
  const sets = Object.keys(a);
  const best = (k) => sets.reduce((m, s) => (a[s][k] > a[m][k] ? s : m), sets[0]);
  const cols = [["zone_4wk_skill", "fc.abl_z4", pct], ["zone_week1_skill", "fc.abl_w1", pct], ["region_4wk_skill", "fc.abl_r4", pct],
    ["bss", "fc.abl_bss", (x) => fmt(x, 3)], ["auc", "fc.abl_auc", (x) => fmt(x, 3)]];
  return `<div class="small strong" style="margin:14px 0 2px">${esc(t("fc.abl_t"))}</div>
    <p class="small muted" style="margin:0 0 8px">${esc(t("fc.abl_h"))}</p>
    <div class="table-wrap"><table class="table ablation"><thead><tr><th></th>
      ${sets.map((s) => `<th class="num" style="text-transform:none;letter-spacing:0">${esc(t("fc.abl_" + s))}${v.feature_set === s ? `<span class="tag">${esc(t("fc.abl_kept"))}</span>` : ""}</th>`).join("")}</tr></thead><tbody>
      ${cols.map(([k, l, f]) => `<tr><td>${esc(t(l))}</td>
        ${sets.map((s) => `<td class="num${best(k) === s ? " win" : ""}">${f(a[s][k])}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>`;
}

export async function render(main) {
  const lang = getLang();
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("fc.kicker"))}</div><h1>${esc(t("fc.title"))}</h1>
    <p class="sub">${esc(t("fc.sub"))}</p></div></div><div id="body">${loadingBlock()}</div>${footer()}`;
  const body = $("#body", main);
  let d, adm1, adm2;
  try {
    [d, adm1, adm2] = await Promise.all([api.get(`/api/forecast?lang=${lang}`), api.get("/api/admin-units?level=1"), api.get("/api/admin-units?level=2")]);
  } catch (e) { body.innerHTML = errorBlock(e.status === 503 ? t("fc.unavailable") : e); return; }
  if (!body.isConnected) return;
  const v = d.validation || {};
  const r = d.region;
  const iss = d.issue;
  const tgtEnd = (h) => { const s = new Date(iss.targets[h - 1].start + "T00:00:00"); s.setDate(s.getDate() + 6); return s.toISOString().slice(0, 10); };
  body.innerHTML = `
    <section class="fc-hero">
      <div class="eyebrow">${esc(t("fc.issued"))} ${esc(fmtDay(iss.week_end))} · ${esc(t("fc.space_apps"))}</div>
      <h2>${esc(t("fc.region"))}${lang === "fr" ? " :" : ":"} ${esc(t("risk." + r.next2.risk)).toLowerCase()} ${lang === "fr" ? "jusqu'au" : "until"} ${esc(fmtDay(tgtEnd(2)))}</h2>
      <div class="story">${forecastStory(inRegion(), r.next2, r.next4, fmtDay(tgtEnd(2))).map((p) => `<p>${p}</p>`).join("")}</div>
      <div class="fc-stats">
        <div><b>${fmtInt(r.next2.mu)}</b><span>${esc(t("fc.expected"))} · ${esc(t("fc.h2"))} (${fmtInt(r.next2.lo)} – ${fmtInt(r.next2.hi)})</span></div>
        <div><b>×${fmt(r.next2.ratio, 2)}</b><span>${esc(t("fc.vs_normal"))} (${esc(t("ex.median"))} ${fmtInt(r.next2.normal)})</span></div>
        <div><b>${v.zone_4wk ? fmt(100 * v.zone_4wk.ml.skill_vs_clim, 0) + PCT() : "–"}</b><span>${esc(lang === "fr" ? "plus précise que la moyenne des années passées (4 semaines)" : "more accurate than the average of past years (4 weeks)")}</span></div>
        <div><b>${v.above_normal ? fmt(v.above_normal.auc_ml, 2) : "–"}</b><span>${esc(lang === "fr" ? "capacité à repérer une quinzaine anormale (0,5 = hasard, 1 = parfait)" : "ability to spot an abnormal fortnight (0.5 = chance, 1 = perfect)")}</span></div>
      </div>
    </section>

    <div class="row" style="margin:18px 0 12px">
      <div class="seg" role="group" aria-label="${esc(t("fc.horizon"))}">
        <button data-h="next2" aria-pressed="${state.horizon === "next2"}">${esc(t("fc.h2"))}</button>
        <button data-h="next4" aria-pressed="${state.horizon === "next4"}">${esc(t("fc.h4"))}</button></div>
      <div class="seg" role="group">
        <button data-l="2" aria-pressed="${state.level === 2}">${esc(t("fc.level2"))}</button>
        <button data-l="1" aria-pressed="${state.level === 1}">${esc(t("fc.level1"))}</button></div>
      <div class="legend" style="margin:0 0 0 auto">${Object.keys(RISK).map((k) => `<span><i class="sw" style="background:${RISK[k].fill}"></i>${esc(t("risk." + k))}</span>`).join("")}</div>
    </div>
    <div class="grid g2">
      <div class="stack" style="gap:0"><div class="map-wrap" style="height:520px"><div class="map" id="fmap"></div></div>${howTo(t("how.fc_map"))}</div>
      <div class="card" id="detail"></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${icons.alert} ${esc(t("fc.where"))}</h3><span class="hint">${esc(t("fc.where_s"))}</span></div>
      <div class="card-body"><div class="table-wrap" id="rank"></div>${howTo(t("how.rank"))}</div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("fc.skill_t"))}</h3><span class="hint">${esc(t("fc.skill_s"))}</span></div>
        <div class="card-body">${v.zone_4wk ? `${plainBox(skillStory(v), { title: t("plain.skill_t") })}<div style="height:14px"></div><div class="kpis">
          <div class="kpi"><div class="label">${esc(t("fc.skill"))}</div><div class="value">${fmt(100 * v.zone_4wk.ml.skill_vs_clim, 0)}${PCT()}</div>
            <div class="note">${lang === "fr" ? "persistance de l'anomalie" : "persisted anomaly"}${COLON()} ${fmt(100 * v.zone_4wk.pers.skill_vs_clim, 0)}${PCT()}</div></div>
          <div class="kpi"><div class="label">${esc(t("fc.bss"))}</div><div class="value">${fmt(v.above_normal.bss_ml, 2)}</div>
            <div class="note">${v.above_normal.bss_raw != null ? `${esc(t("fc.bss_raw"))}${COLON()} ${fmt(v.above_normal.bss_raw, 2)} · ` : ""}${lang === "fr" ? "persistance" : "persistence"}${COLON()} ${fmt(v.above_normal.bss_pers, 2)}</div></div>
          <div class="kpi"><div class="label">${esc(t("fc.auc"))}</div><div class="value">${fmt(v.above_normal.auc_ml, 2)}</div>
            <div class="note">${lang === "fr" ? "persistance" : "persistence"}${COLON()} ${fmt(v.above_normal.auc_pers, 2)}</div></div>
          <div class="kpi"><div class="label">${esc(t("fc.cov"))}</div><div class="value">${fmt(100 * v.coverage_4wk, 0)}${PCT()}</div>
            <div class="note">κ = ${fmt(v.kappa_4wk, 2)}</div></div></div>
          <div class="grid g2" style="margin-top:6px;align-items:start">
            <div><div class="small strong" style="margin:14px 0 4px">${esc(t("fc.reliab"))} <span class="muted">· ${esc(t("fc.reliab_h"))}</span></div>
              <div class="chart" id="c-rel"></div><div id="l-rel"></div>${howTo(t("how.rel"))}</div>
            <div>${ablationHtml(v)}</div>
          </div>` : `<p class="muted">–</p>`}</div></div>
    <div class="card card-pad" style="margin-top:16px"><h3 style="font-size:15.5px;margin-bottom:10px">${icons.spark} ${esc(t("fc.how_t"))}</h3>
      <ol style="margin:0;padding-left:20px;display:grid;gap:8px;max-width:980px">${t("fc.how").map((p) => `<li class="ink2">${esc(p)}</li>`).join("")}</ol>
      <p class="small muted" style="margin-top:12px">${lang === "fr" ? "Données : NASA FIRMS (MODIS, VIIRS S-NPP, NOAA-20, NOAA-21) jusqu'au" : "Data: NASA FIRMS (MODIS, VIIRS S-NPP, NOAA-20, NOAA-21) up to"} ${esc(fmtDay(iss.week_end))}.</p></div>`;

  const units = () => d.units.filter((u) => u.level === state.level);
  const sorted = () => [...units()].sort((a, b) => (ORDER[a[state.horizon].risk] - ORDER[b[state.horizon].risk]) || (b[state.horizon].mu - a[state.horizon].mu));

  function drawRank() {
    const every = sorted();
    // by default: the units where something is to be done (at least 10 rows)
    const active = every.filter((u) => u[state.horizon].risk !== "offseason");
    const rows = state.all ? every : (active.length >= 10 ? active : every.slice(0, 10));
    const max = Math.max(...rows.map((u) => u[state.horizon].mu), 1);
    $("#rank", body).innerHTML = `<table class="table rank-table"><thead><tr><th>#</th><th>${esc(t(state.level === 2 ? "common.department" : "common.region"))}</th>
      <th>${esc(t("common.status"))}</th><th class="num">${esc(t("fc.expected"))}</th><th style="width:16%"></th><th class="num">${esc(t("fc.vs_normal"))}</th>
      <th class="num">${esc(t("fc.prob_above"))}</th><th></th></tr></thead><tbody>
      ${rows.map((u, i) => { const b = u[state.horizon]; return `<tr data-id="${esc(u.id)}" style="cursor:pointer">
        <td class="muted">${i + 1}</td><td><b>${esc(u.name)}</b> <span class="muted small">${esc(u.parent || u.iso3)}</span></td>
        <td>${riskChip(b.risk)}</td><td class="num">${fmtInt(b.mu)} <span class="muted small">(${fmtInt(b.lo)}–${fmtInt(b.hi)})</span></td>
        <td><div class="bar" style="width:${Math.max(2, 100 * b.mu / max)}%"></div></td>
        <td class="num">×${fmt(b.ratio, 1)}</td><td class="num">${b.prob_above != null ? fmt(100 * b.prob_above, 0) + PCT() : "–"}</td>
        <td><button class="btn sm ghost" data-msg="${esc(u.id)}" aria-label="${esc(t("fc.sms_t"))}">${icons.sms}</button></td></tr>`; }).join("")}</tbody></table>
      ${rows.length < every.length || state.all ? `<div class="row" style="justify-content:center;margin-top:10px">
        <button class="btn sm" id="rank-more">${esc(state.all ? t("fc.show_less") : t("fc.show_all").replace("{n}", every.length))}</button>
        ${state.all ? "" : `<span class="small muted">${esc(t("fc.hidden_low").replace("{n}", every.length - rows.length))}</span>`}</div>` : ""}`;
    $$("#rank tr[data-id]", body).forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.id)));
    $("#rank-more", body)?.addEventListener("click", () => { state.all = !state.all; drawRank(); });
  }

  async function select(id) {
    state.sel = id;
    const u = d.units.find((x) => x.id === id);
    const det = $("#detail", body);
    if (!u) {
      det.innerHTML = `<div class="card-head"><h3>${esc(t("fc.region"))}</h3></div><div class="card-body">
        <div class="story" style="margin-bottom:10px">${forecastStory(inRegion(), r.next2, r.next4, fmtDay(tgtEnd(2))).map((p) => `<p>${p}</p>`).join("")}</div>
        <div id="c-fc"></div><div id="l-fc"></div>${howTo(t("how.fc"))}<div style="margin-top:12px">${smsCard(r.message)}</div></div>`;
      $("#l-fc", det).innerHTML = charts.forecastChart($("#c-fc", det), r);
      bindCopy(det, r.message);
      return;
    }
    det.innerHTML = `<div class="card-head"><h3>${esc(u.name)}</h3><span class="hint">${esc(u.parent || u.iso3)}</span>
      <div class="tools"><a class="btn sm" href="#/explorer">${icons.map}${esc(t("nav.explorer_short"))}</a></div></div>
      <div class="card-body">
      <div class="story" style="margin-bottom:12px">${forecastStory(inPlace(u.name), u.next2, u.next4, fmtDay(tgtEnd(2))).map((p) => `<p>${p}</p>`).join("")}</div>
      <div class="grid g2" style="gap:10px">${blockHtml(u.next2, t("fc.next2"))}${blockHtml(u.next4, t("fc.next4"))}</div>
      <div id="c-fc" style="margin-top:10px"><div class="progress"></div></div><div id="l-fc"></div>${howTo(t("how.fc"))}
      <div style="margin-top:12px">${smsCard(u.message)}</div></div>`;
    bindCopy(det, u.message);
    const gj = (state.level === 2 ? adm2 : adm1).features.find((f) => f.properties.id === id);
    try {
      const z = await api.post("/api/zone/forecast", { geometry: gj.geometry, name: u.name, lang });
      if (state.sel !== id || !det.isConnected) return;
      $("#l-fc", det).innerHTML = charts.forecastChart($("#c-fc", det), z);
    } catch (e) { $("#c-fc", det).innerHTML = `<p class="muted small">${esc(e.message)}</p>`; }
    fm.map.getSource("units") && highlight(id);
  }

  const fm = new FireMap($("#fmap", body), { zoom: 5.5 });
  function unitFC() {
    const gj = state.level === 2 ? adm2 : adm1;
    const byId = Object.fromEntries(units().map((u) => [u.id, u]));
    return { type: "FeatureCollection", features: gj.features.filter((f) => byId[f.properties.id]).map((f) => {
      const u = byId[f.properties.id];
      return { type: "Feature", geometry: f.geometry, properties: { id: u.id, name: u.name, risk: u[state.horizon].risk, mu: u[state.horizon].mu, ratio: u[state.horizon].ratio } };
    }) };
  }
  function highlight(id) {
    if (fm.map.getLayer("units-sel")) fm.map.setFilter("units-sel", ["==", ["get", "id"], id || ""]);
  }
  async function drawMap() {
    await fm.ready;
    const data = unitFC();
    if (fm.map.getSource("units")) fm.map.getSource("units").setData(data);
    else {
      fm.map.addSource("units", { type: "geojson", data });
      fm.map.addLayer({ id: "units-fill", type: "fill", source: "units", paint: {
        "fill-color": ["match", ["get", "risk"], ...Object.entries(RISK).flatMap(([k, x]) => [k, x.fill]), "#b8b2a8"], "fill-opacity": 0.62 } });
      fm.map.addLayer({ id: "units-line", type: "line", source: "units", paint: { "line-color": isDark() ? "#0f0d0c" : "#ffffff", "line-width": 1 } });
      fm.map.addLayer({ id: "units-sel", type: "line", source: "units", filter: ["==", ["get", "id"], ""], paint: { "line-color": "#1d1b19", "line-width": 2.6 } });
      fm.map.on("click", "units-fill", (e) => select(e.features[0].properties.id));
      fm.map.on("mouseenter", "units-fill", () => { fm.map.getCanvas().style.cursor = "pointer"; });
      fm.map.on("mouseleave", "units-fill", () => { fm.map.getCanvas().style.cursor = ""; });
    }
  }
  $$("[data-h]", body).forEach((b) => b.addEventListener("click", () => {
    state.horizon = b.dataset.h; $$("[data-h]", body).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    drawRank(); drawMap(); if (state.sel) select(state.sel);
  }));
  $$("[data-l]", body).forEach((b) => b.addEventListener("click", () => {
    state.level = +b.dataset.l; state.sel = null; $$("[data-l]", body).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    drawRank(); drawMap(); select(sorted()[0]?.id);
  }));
  drawRank();
  drawMap();
  select(state.sel && units().some((u) => u.id === state.sel) ? state.sel : sorted()[0]?.id);
  const drawRel = () => {
    if (!v.above_normal || !$("#c-rel", body)) return;
    $("#l-rel", body).innerHTML = charts.reliabilityChart($("#c-rel", body), v.above_normal.reliability, v.above_normal.reliability_raw || null);
  };
  drawRel();
  const onR = () => drawRel();
  window.addEventListener("fs-resize", onR);
  return () => { window.removeEventListener("fs-resize", onR); fm.remove(); };
}
