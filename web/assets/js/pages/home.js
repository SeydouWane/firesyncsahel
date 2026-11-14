import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, esc, icons, fmtInt, fmt, cssVar, riskChip } from "../ui.js";
import { logoSVG } from "../logo.js";
import * as charts from "../charts.js";
import { FS } from "../main.js";
import { dataStrip, partnersBlock, partnerLogos, footer } from "./data.js";

export async function render(main) {
  const m = FS.meta;
  const nDet = m ? m.sensors.reduce((a, s) => a + s.n, 0) : null;
  const gbm = m?.validation?.gbm;
  main.innerHTML = `
    <section class="hero">
      <svg class="hex-bg" viewBox="0 0 600 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs><pattern id="hx" width="34" height="58.9" patternUnits="userSpaceOnUse" patternTransform="scale(1.1)">
          <path d="M17 0l17 9.8v19.6L17 39.3 0 29.4V9.8z M17 39.3v19.6" fill="none" stroke="#fff" stroke-width="1"/></pattern></defs>
        <rect width="600" height="300" fill="url(#hx)"/></svg>
      <div class="hero-grid">
        <div>
          <div class="eyebrow" style="color:#ffd27a">${esc(t("home.kicker"))}</div>
          <h1>${t("home.title")}</h1>
          <p class="lead">${esc(t("home.lead"))}</p>
          <div class="row"><a class="btn lg primary" href="#/explorer">${icons.map}${esc(t("home.cta"))}</a>
            <a class="btn lg ghost" href="#/forecast">${icons.spark}${esc(t("fc.title"))}</a></div>
          <div class="hero-partners"><span class="small">${esc(t("fc.space_apps"))}</span>${partnerLogos("hero")}</div>
        </div>
        <div class="hero-logo">${logoSVG({ size: 300 })}</div>
      </div>
      <div class="hero-stats">
        <div><b>${m ? 2000 + "–" + m.last_date.slice(0, 4) : "25+"}</b><span>${esc(t("home.s_years"))}</span></div>
        <div><b>${nDet ? fmt(nDet / 1e6, 1) + " M" : "–"}</b><span>${esc(t("home.s_det"))}</span></div>
        <div><b>5</b><span>${esc(t("home.s_sensors"))} · Terra · Aqua · S-NPP · NOAA-20 · NOAA-21</span></div>
        <div><b>${gbm ? fmt(gbm.zone_week_nmae, 0) + " %" : "–"}</b><span>${esc(t("home.s_err"))}</span></div>
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.why_t"))}</h2><p class="sub">${esc(t("home.why_s"))}</p>
      <div class="card"><div class="card-body" style="padding-top:16px">
        <div id="why-legend"></div><div class="chart" id="why-chart"><div class="progress"></div></div>
        <p class="small muted" style="margin:6px 0 0">${esc(t("common.unit"))} · ${m ? esc(m.countries.join(", ").replace(/_/g, " ")) : ""}</p>
      </div></div>
    </section>

    <section class="section">
      <h2>${icons.spark} ${esc(t("fc.title"))}</h2><p class="sub">${esc(t("fc.sub"))}</p>
      <div class="card" id="home-fc"><div class="card-body"><div class="progress"></div></div></div>
    </section>

    <section class="section">
      <h2>${esc(t("home.p_title"))}</h2>
      <div class="grid g3">
        ${[["cpu", 1], ["map", 2], ["chart", 3]].map(([ic, i]) => `<div class="card pillar"><div class="ic">${icons[ic]}</div>
          <h3>${esc(t(`home.p${i}_t`))}</h3><p>${esc(t(`home.p${i}_d`))}</p></div>`).join("")}
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.aud_t"))}</h2><p class="sub">${esc(t("home.aud_s"))}</p>
      <div class="grid g2">
        ${[["tree", 1], ["cow", 2], ["lab", 3], ["bell", 4]].map(([ic, i]) => `<div class="card audience"><div class="ic">${icons[ic]}</div>
          <div><h4>${esc(t(`home.a${i}_t`))}</h4><p>${esc(t(`home.a${i}_d`))}</p></div></div>`).join("")}
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.data_t"))}</h2><p class="sub">${esc(t("home.data_s"))}</p>
      ${dataStrip()}
      <div class="card card-pad" style="margin-top:14px;display:flex;gap:12px;align-items:center">
        <span class="chip brand">${icons.sat}NOAA-20 · NOAA-21</span><span class="ink2">${esc(t("home.snpp"))}</span></div>
      ${partnersBlock()}
    </section>
    ${footer()}`;

  let data = null;
  const draw = () => {
    if (!data || !main.isConnected || !$("#why-chart", main)) return;
    const h = data.harmonized.filter((y) => y.complete && y.total != null);
    const n = data.naive.filter((y) => y.complete && y.total != null);
    const colH = cssVar("--brand"), colN = cssVar("--muted");
    const series = [
      { key: "n", label: t("home.naive"), short: getLang() === "fr" ? "naïf" : "naive", color: colN, values: n.map((y) => ({ x: y.fyear, y: y.total })) },
      { key: "h", label: t("home.harm"), short: "FireSync", color: colH, values: h.map((y) => ({ x: y.fyear, y: y.total })) },
    ];
    charts.lines($("#why-chart", main), series, { height: 280,
      interval: { color: colH, values: h.map((y) => ({ x: y.fyear, lo: y.total_lo, hi: y.total_hi })) } });
    $("#why-legend", main).innerHTML = charts.legendHtml([...series, { label: t("home.interval"), color: colH + "44" }]);
  };
  const fcBox = $("#home-fc", main);
  api.get(`/api/forecast?lang=${getLang()}`).then((f) => {
    if (!fcBox.isConnected) return;
    const r = f.region.next2;
    const order = { high: 0, moderate: 1, low: 2, offseason: 3 };
    const top = f.units.filter((u) => u.level === 2)
      .sort((a, b) => (order[a.next2.risk] - order[b.next2.risk]) || (b.next2.mu - a.next2.mu)).slice(0, 5);
    fcBox.innerHTML = `<div class="card-body" style="padding-top:16px"><div class="grid g2">
      <div><div class="row" style="gap:8px;margin-bottom:8px">${riskChip(r.risk)}<span class="small muted">${esc(t("fc.issued"))} ${esc(f.issue.week_end)}</span></div>
        <div style="font-size:30px;font-weight:800;letter-spacing:-.02em">~${fmtInt(r.mu)} <span class="small ink2" style="font-size:14px;font-weight:600">${esc(t("fc.expected"))} · ${esc(t("fc.h2"))}</span></div>
        <div class="ink2 small">×${fmt(r.ratio, 2)} ${esc(t("fc.vs_normal"))} · ${esc(t("fc.interval"))} ${fmtInt(r.lo)} – ${fmtInt(r.hi)}</div>
        <div class="sms" style="margin-top:12px">${esc(f.region.message)}</div>
        <a class="btn primary" href="#/forecast" style="margin-top:12px">${icons.spark}${esc(t("fc.title"))} →</a></div>
      <div><div class="small strong muted" style="margin-bottom:6px">${esc(t("fc.where"))}</div>
        <table class="table"><tbody>${top.map((u, i) => `<tr><td class="muted">${i + 1}</td><td><b>${esc(u.name)}</b> <span class="muted small">${esc(u.parent || "")}</span></td>
          <td>${riskChip(u.next2.risk)}</td><td class="num">~${fmtInt(u.next2.mu)}</td></tr>`).join("")}</tbody></table></div>
    </div></div>`;
  }).catch(() => { if (fcBox.isConnected) fcBox.innerHTML = `<div class="card-body muted small">${esc(t("fc.unavailable"))}</div>`; });

  api.get(`/api/region/summary?lang=${getLang()}`).then((d) => { data = d; draw(); })
    .catch((e) => { const el = $("#why-chart", main); if (el) el.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; });
  const onR = () => draw();
  window.addEventListener("fs-resize", onR);
  return () => window.removeEventListener("fs-resize", onR);
}
