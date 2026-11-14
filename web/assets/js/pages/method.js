import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, esc, fmt, fmtInt, fmtSigned, loadingBlock, errorBlock, cssVar, icons } from "../ui.js";
import * as charts from "../charts.js";
import { footer } from "./data.js";

const MODELS = ["naive", "single_ratio", "stratified_eb", "gbm"];
const SCALES = ["cell_week", "zone_week", "region_week", "zone_year", "region_year"];

export async function render(main, { space }) {
  const l = getLang();
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t(space === "admin" ? "space.admin" : "space.public"))}</div>
    <h1>${esc(t("method.title"))}</h1><p class="sub">${esc(t("method.sub"))}</p></div></div><div id="body">${loadingBlock()}</div>${space === "admin" ? "" : footer()}`;
  const body = $("#body", main);
  let d;
  try { d = await api.get("/api/validation"); } catch (e) { body.innerHTML = errorBlock(e.status === 404 ? t("method.not_run") : e); return; }
  if (!body.isConnected) return;
  main = body;  // later lookups are scoped to this page's own (possibly detached) DOM
  const rep = d.report, ta = rep.variants.TA, tv = rep.variants.T;
  const lab = Object.fromEntries(MODELS.map((m) => [m, rep.models[m]?.[l] || m]));
  const st = d.step_test || {};
  const pair = rep.pairing || {};
  const vc = rep.viirs_continuity || {};
  const vc21 = rep.viirs_continuity_n21 || {};
  const steps = l === "fr" ? [
    ["Ingestion", "Archives annuelles FIRMS (MODIS C6.1, VIIRS S-NPP, NOAA-20) + temps quasi réel ; filtres type 0 et confiance."],
    ["Grille hexagonale", "Agrégation hebdomadaire sur H3 : résolution 7 (~5 km²) pour les requêtes, résolution 5 (~250 km²) pour le modèle."],
    ["Disponibilité des capteurs", "Détection des pannes et fins de mission, correction des semaines partielles."],
    ["Appariement des passages", "Passages Aqua / S-NPP et NOAA-20 / S-NPP à ±60 min, voisinage co-observé."],
    ["Modèle", "Gradient boosting de Poisson par variante (Terra+Aqua, Terra seul, Aqua seul), ensemble bootstrap sur les années, a priori par cellule, saison et couvert (MCD12Q1)."],
    ["Incertitude", "Membres de l'ensemble + bruit binomial négatif, facteur κ calibré pour une couverture réelle de 90 %."],
    ["Continuité VIIRS", "NOAA-20 / NOAA-21 → équivalent S-NPP par cellule et saison, pour l'après-2026."],
  ] : [
    ["Ingestion", "FIRMS yearly archives (MODIS C6.1, VIIRS S-NPP, NOAA-20) + near real time; type-0 and confidence filters."],
    ["Hexagonal grid", "Weekly aggregation on H3: resolution 7 (~5 km²) for queries, resolution 5 (~250 km²) for the model."],
    ["Sensor availability", "Outage and end-of-mission detection, partial-week correction."],
    ["Overpass pairing", "Aqua / S-NPP and NOAA-20 / S-NPP passes within ±60 min, co-observed neighbourhood."],
    ["Model", "Poisson gradient boosting per variant (Terra+Aqua, Terra only, Aqua only), bootstrap ensemble over years, priors by cell, season and land cover (MCD12Q1)."],
    ["Uncertainty", "Ensemble members + negative-binomial noise, κ factor calibrated to a true 90% coverage."],
    ["VIIRS continuity", "NOAA-20 / NOAA-21 → S-NPP equivalent per cell and season, for post-2026."],
  ];
  const tableFor = (variant, key = "loyo") => {
    const v = rep.variants[variant];
    return `<div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("method.scale"))}</th>
      ${MODELS.map((m) => `<th class="num">${esc(lab[m])}</th>`).join("")}</tr></thead><tbody>
      ${SCALES.map((s) => `<tr><td>${esc(t("method.scales." + s))}</td>${MODELS.map((m) => {
        const x = v[m]?.[key]?.[s];
        const cov = key === "loyo" && v[m]?.loyo_scaled_coverage ? v[m].loyo_scaled_coverage[s] : x?.coverage90;
        return `<td class="num">${x ? `${fmt(x.nmae_pct, 1)} %<br><span class="muted small">${fmtSigned(x.bias_pct, 1, " %")}${cov != null ? " · " + fmt(100 * cov, 0) + " %" : ""}</span>` : "–"}</td>`;
      }).join("")}</tr>`).join("")}
      <tr><td>${esc(t("method.onset_err"))} / ${esc(t("method.peak_err"))} / ${esc(t("method.end_err"))}</td>${MODELS.map((m) => {
        const z = v[m]?.[key === "loyo" ? "season_loyo" : "season_out_of_window"]?.zone;
        return `<td class="num">${z ? `${fmt(z.onset, 1)} / ${fmt(z.peak, 1)} / ${fmt(z.end, 1)}` : "–"}</td>`;
      }).join("")}</tr></tbody></table></div>
      <p class="small muted" style="margin-top:6px">${l === "fr" ? "Cellule : erreur absolue normalisée ; dessous : biais · couverture de l'intervalle 90 %." : "Cell: normalised absolute error; below: bias · 90% interval coverage."}</p>`;
  };
  body.innerHTML = `
    <div class="kpis">
      <div class="kpi hl"><div class="label">${esc(t("method.nmae"))} · ${esc(t("method.scales.zone_week"))}</div>
        <div class="value">${fmt(ta.gbm.loyo.zone_week.nmae_pct, 0)} %</div><div class="note">${esc(lab.single_ratio)} : ${fmt(ta.single_ratio.loyo.zone_week.nmae_pct, 0)} % · ${esc(lab.naive)} : ${fmt(ta.naive.loyo.zone_week.nmae_pct, 0)} %</div></div>
      <div class="kpi"><div class="label">${esc(t("method.bias"))} · ${esc(t("method.scales.region_year"))}</div>
        <div class="value">${fmtSigned(ta.gbm.loyo.region_year.bias_pct, 1, " %")}</div><div class="note">${esc(lab.naive)} : ${fmtSigned(ta.naive.loyo.region_year.bias_pct, 0, " %")}</div></div>
      <div class="kpi"><div class="label">${esc(t("method.coverage"))}</div><div class="value">${fmt(100 * ta.gbm.loyo.zone_week.coverage90, 0)} %</div>
        <div class="note">κ = ${fmt(ta.gbm.kappa, 2)} · ${l === "fr" ? "brut" : "raw"} ${fmt(100 * (ta.gbm.kappa_raw_coverage || 0), 0)} %</div></div>
      <div class="kpi"><div class="label">${esc(t("method.step_harm"))}</div><div class="value">×${fmt(st.step_harmonised, 2)}</div>
        <div class="note">${esc(t("method.step_naive"))} : ×${fmt(st.step_naive, 2)} · ${esc(t("method.step_ideal"))}</div></div>
    </div>

    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>${esc(t("method.models"))}</h3><span class="hint">${esc(t("method.nmae"))} · ${esc(t("method.loyo"))}</span></div>
        <div class="card-body"><div id="leg-models"></div><div class="chart" id="c-models"></div></div></div>
      <div class="card"><div class="card-head"><h3>${esc(t("method.step_t"))}</h3></div><div class="card-body">
        <p class="small ink2">${esc(t("method.step_d"))}</p><div id="leg-step"></div><div class="chart" id="c-step"></div></div></div>
    </div>

    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("method.loyo"))} — Terra + Aqua</h3>
      <span class="hint">${esc(t("train" in rep ? "" : ""))}${l === "fr" ? "années de feu" : "fire years"} ${rep.train_fire_years[0]}–${rep.train_fire_years.at(-1)} · ${esc(t("method.lc_used"))} : ${esc(rep.land_cover?.product || "–")}</span></div>
      <div class="card-body">${tableFor("TA")}</div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("method.loyo"))} — Terra ${l === "fr" ? "seul (2000–2002)" : "only (2000–2002)"}</h3></div><div class="card-body">${tableFor("T")}</div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("method.oow"))}</h3><span class="hint">${l === "fr" ? "années de feu" : "fire years"} ${rep.test_fire_years.join(", ")}</span></div><div class="card-body">${tableFor("TA", "out_of_window")}</div></div>

    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>${esc(t("method.drift_t"))}</h3></div><div class="card-body">
        <p class="small ink2">${esc(t("method.drift_d"))}</p><div id="leg-drift"></div><div class="chart" id="c-drift"></div></div></div>
      <div class="stack">
        <div class="card card-pad"><h3 style="font-size:15px;margin-bottom:8px">${esc(t("method.pair_t"))}</h3><p class="small ink2">${esc(t("method.pair_d"))}</p>
          <div class="kpis"><div class="kpi"><div class="label">${esc(t("method.inst"))}</div><div class="value">×${fmt(pair.instantaneous_ratio, 2)}</div>
            <div class="note">${fmtInt(pair.matched_aqua_detections)} ${l === "fr" ? "détections Aqua appariées" : "matched Aqua detections"}</div></div>
            <div class="kpi"><div class="label">${esc(t("method.weekly"))}</div><div class="value">×${fmt(pair.weekly_ratio_V_over_A, 2)}</div>
            <div class="note">${l === "fr" ? "inclut l'échantillonnage (fauchée, revisite)" : "includes sampling (swath, revisit)"}</div></div></div></div>
        <div class="card card-pad"><h3 style="font-size:15px;margin-bottom:8px">${esc(t("method.viirs_t"))}</h3>
          <div class="kpis"><div class="kpi"><div class="label">${esc(t("method.nmae"))}</div><div class="value">${fmt(vc.metrics?.zone_week?.nmae_pct, 0)} %</div>
            <div class="note">${l === "fr" ? "brut" : "raw"} NOAA-20 : ${fmt(vc.naive_metrics?.zone_week?.nmae_pct, 0)} %</div></div>
            <div class="kpi"><div class="label">${esc(t("method.bias"))}</div><div class="value">${fmtSigned(vc.metrics?.region_year?.bias_pct, 1, " %")}</div>
            <div class="note">S-NPP / NOAA-20 ×${fmt(vc.global_ratio, 3)}</div></div></div>
          ${vc21.metrics ? `<h3 style="font-size:15px;margin:14px 0 8px">NOAA-21 → S-NPP <span class="muted small">(${esc(vc21.period?.join("–") || "")})</span></h3>
          <div class="kpis"><div class="kpi"><div class="label">${esc(t("method.nmae"))}</div><div class="value">${fmt(vc21.metrics.zone_week?.nmae_pct, 0)} %</div>
            <div class="note">${l === "fr" ? "brut" : "raw"} NOAA-21 : ${fmt(vc21.naive_metrics?.zone_week?.nmae_pct, 0)} %</div></div>
            <div class="kpi"><div class="label">${esc(t("method.bias"))}</div><div class="value">${fmtSigned(vc21.metrics.region_year?.bias_pct, 1, " %")}</div>
            <div class="note">S-NPP / NOAA-21 ×${fmt(vc21.global_ratio, 3)}</div></div></div>` : ""}</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("method.steps_t"))}</h3></div><div class="card-body">
      <ol style="margin:0;padding-left:20px;display:grid;gap:8px">${steps.map(([a, b]) => `<li><b>${esc(a)}</b> — <span class="ink2">${esc(b)}</span></li>`).join("")}</ol></div></div>`;

  const draw = () => {
    if (!main.isConnected || !$("#c-models", main)) return;
    const rows = ["zone_week", "region_week", "zone_year", "region_year"].map((s) => ({ g: s, ...Object.fromEntries(MODELS.map((m) => [m, ta[m]?.loyo?.[s]?.nmae_pct])) }));
    $("#leg-models", main).innerHTML = charts.groupedBars($("#c-models", main), rows, {
      groups: rows.map((r) => ({ key: r.g, label: t("method.scales." + r.g) })), keys: MODELS, labels: lab });
    if (st.annual) {
      const colN = cssVar("--muted"), colH = cssVar("--brand");
      const ser = [
        { key: "n", label: t("home.naive"), short: l === "fr" ? "naïf" : "naive", color: colN, values: st.annual.map((r) => ({ x: r.fyear, y: r.N / r.ba_km2 })) },
        { key: "h", label: t("home.harm"), short: "FireSync", color: colH, values: st.annual.map((r) => ({ x: r.fyear, y: r.H / r.ba_km2 })) },
      ];
      charts.lines($("#c-step", main), ser, { height: 230, yFormat: (v) => fmt(v, 2) });
      $("#leg-step", main).innerHTML = charts.legendHtml(ser) + `<p class="small muted" style="margin:0">${l === "fr" ? "détections par km² brûlé (MCD64A1)" : "detections per burned km² (MCD64A1)"}</p>`;
    }
    const dr = (rep.drift || []).filter((r) => r.fyear >= 2012 && r.fyear <= 2024);
    const ser2 = [
      { key: "t", label: "VIIRS / Terra", short: "/ Terra", color: cssVar("--src-modis"), values: dr.map((r) => ({ x: r.fyear, y: r.V_T })) },
      { key: "a", label: "VIIRS / Aqua", short: "/ Aqua", color: "#eda100", values: dr.map((r) => ({ x: r.fyear, y: r.V_A })) },
      { key: "n", label: "S-NPP / NOAA-20", short: "/ NOAA-20", color: cssVar("--src-n20"), values: dr.filter((r) => r.V_N20 && r.fyear >= 2018).map((r) => ({ x: r.fyear, y: r.V_N20 })) },
    ];
    charts.lines($("#c-drift", main), ser2, { height: 230, yFormat: (v) => fmt(v, 1) });
    $("#leg-drift", main).innerHTML = charts.legendHtml(ser2);
  };
  draw();
  const onR = () => draw();
  window.addEventListener("fs-resize", onR);
  return () => window.removeEventListener("fs-resize", onR);
}
