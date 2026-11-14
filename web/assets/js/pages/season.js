import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, esc, icons, fmtInt, fmt, statusChip, loadingBlock, errorBlock, STATUS, cssVar } from "../ui.js";
import { FireMap, isDark } from "../map.js";
import { footer } from "./data.js";
import { plainBox, howTo, seasonStory } from "../explain.js";

const ORDER = ["above_p90", "p75_p90", "normal", "p10_p25", "below_p10", "offseason", "nodata"];
const FILL = { above_p90: "#d03b3b", p75_p90: "#fab219", normal: "#0ca30c", p10_p25: "#9a958c", below_p10: "#6f6a62", offseason: "#c3c2b7", nodata: "#c3c2b7" };

export async function render(main) {
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("space.public"))}</div><h1>${esc(t("season.title"))}</h1>
    <p class="sub">${esc(t("season.sub"))}</p></div></div><div id="body">${loadingBlock()}</div>${footer()}`;
  const body = $("#body", main);  // captured: stays ours even if the user navigates away
  let d;
  try { d = await api.get(`/api/season/overview?lang=${getLang()}`); }
  catch (e) { body.innerHTML = errorBlock(e); return; }
  if (!body.isConnected) return;
  const L = d.week_labels;
  const reg = d.region;
  if (!reg) { body.innerHTML = `<div class="card card-pad">${esc(t("season.none"))}</div>`; return; }
  // regions with too little activity to compare go last (their percentile means nothing)
  const weak = (r) => ["few", "offseason", "nodata"].includes(r.cumulative_status || "nodata");
  const rows = [...d.regions].sort((a, b) => (weak(a) - weak(b)) || ((b.cumulative_pct ?? -1) - (a.cumulative_pct ?? -1)) || (b.cumulative - a.cumulative));
  const ls = reg.last_status || {};
  body.innerHTML = `
    ${plainBox(seasonStory(d), { title: t("plain.season_t") })}
    <div style="height:16px"></div>
    <div class="kpis">
      <div class="kpi hl"><div class="label">${esc(t("ex.current"))}</div><div class="value">${esc(reg.label)}</div>
        <div class="note">${esc(t("ex.last_week"))} : ${esc(L[reg.last_fweek] || "–")}</div></div>
      <div class="kpi"><div class="label">${esc(t("ex.last_week"))}</div><div class="value" style="font-size:15px;margin-top:8px">${statusChip(ls.status)}</div>
        <div class="note">${fmtInt(ls.value)} · ${esc(t("ex.pct"))} ${fmt(ls.pct, 0)}</div></div>
      <div class="kpi"><div class="label">${esc(t("ex.cum"))}</div><div class="value">${fmtInt(reg.cumulative)}</div>
        <div class="note">${esc(t("ex.pct"))} ${fmt(reg.cumulative_pct, 0)} · ${esc(t("ex.median"))} ${fmtInt(reg.clim_cum_median)}</div></div>
      <div class="kpi"><div class="label">${esc(t("ex.onset"))} · ${esc(t("ex.peak"))}</div><div class="value" style="font-size:18px">${esc(L[d.summary.onset] || "–")} · ${esc(L[d.summary.peak] || "–")}</div>
        <div class="note">${esc(t("ex.median"))}</div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="stack" style="gap:0"><div class="map-wrap" style="height:460px"><div class="map" id="smap"></div>
        <div class="map-panel map-legend small">${ORDER.slice(0, 5).map((s) => `<div class="row" style="gap:6px"><i class="sw" style="display:inline-block;width:11px;height:11px;border-radius:3px;background:${FILL[s]}"></i>${esc(t("status." + s))}</div>`).join("")}</div></div>
        ${howTo(t("how.season_map"))}</div>
      <div class="card"><div class="card-head"><h3>${esc(t("season.regions"))}</h3><span class="hint">${esc(t("ex.cum"))} ${esc(t("ex.vs_hist"))}</span></div>
        <div class="card-body"><div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("common.region"))}</th><th>${esc(t("common.status"))}</th>
          <th class="num">${esc(t("ex.cum"))}</th><th class="num">${esc(t("ex.pct"))}</th></tr></thead><tbody>
          ${rows.map((r) => `<tr><td><a href="#/explorer" data-id="${esc(r.id)}">${esc(r.name)}</a> <span class="muted small">${esc(r.iso3)}</span></td>
            <td>${statusChip(r.cumulative_status)}</td><td class="num">${fmtInt(r.cumulative)}</td><td class="num">${weak(r) ? "–" : fmt(r.cumulative_pct, 0)}</td></tr>`).join("")}
          </tbody></table></div>${howTo(t("how.season_table"))}</div></div>
    </div>`;
  const fm = new FireMap($("#smap", body), { zoom: 5.4 });
  await fm.ready;
  const fc = { type: "FeatureCollection", features: d.regions.map((r) => ({ type: "Feature", properties: { name: r.name, s: r.cumulative_status || "nodata", p: r.cumulative_pct }, geometry: r.geometry })) };
  fm.map.addSource("reg", { type: "geojson", data: fc });
  fm.map.addLayer({ id: "reg-fill", type: "fill", source: "reg", paint: { "fill-color": ["match", ["get", "s"], ...ORDER.flatMap((s) => [s, FILL[s]]), "#c3c2b7"], "fill-opacity": 0.55 } });
  fm.map.addLayer({ id: "reg-line", type: "line", source: "reg", paint: { "line-color": isDark() ? "#0f0d0c" : "#fff", "line-width": 1.2 } });
  return () => fm.remove();
}
