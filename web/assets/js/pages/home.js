import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, esc, icons, fmtInt, fmt, fmtDay, cssVar, riskChip, statusChip, copyText, toast } from "../ui.js";
import { logoSVG } from "../logo.js";
import * as charts from "../charts.js";
import { FS } from "../main.js";
import { dataStrip, partnersBlock, partnerLogos, footer } from "./data.js";
import { forecastStory, seasonStory, inRegion, howTo, about } from "../explain.js";

const TASKS = [
  ["spark", 1, "#/forecast"], ["map", 2, "#/explorer"], ["calendar", 3, "#/season"], ["bell", 4, "#/about"],
];
const STEPS = [["sat", 1], ["layers", 2], ["shield", 3], ["sms", 4]];

export async function render(main) {
  const m = FS.meta;
  const nDet = m ? m.sensors.reduce((a, s) => a + s.n, 0) : null;
  const fr = getLang() === "fr";
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
          <div class="row"><a class="btn lg primary" href="#/forecast">${icons.spark}${esc(t("home.cta_fc"))}</a>
            <a class="btn lg ghost" href="#/explorer">${icons.map}${esc(t("home.cta"))}</a></div>
          <div class="hero-partners"><span class="small">${esc(t("fc.space_apps"))}</span>${partnerLogos("hero")}</div>
        </div>
        <div class="hero-logo">${logoSVG({ size: 300 })}</div>
      </div>
      <div class="hero-stats">
        <div><b>${esc(t("home.s_years_v"))}</b><span>${esc(t("home.s_years"))}</span></div>
        <div><b>${nDet ? fmt(nDet / 1e6, 1) + (fr ? " millions" : " million") : "–"}</b><span>${esc(t("home.s_det"))}</span></div>
        <div><b>5 satellites</b><span>${esc(t("home.s_sensors"))}</span></div>
        <div><b>${esc(t("home.s_rel_v"))}</b><span>${esc(t("home.s_rel"))}</span></div>
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.now_t"))}</h2><p class="sub">${esc(t("home.now_s"))}</p>
      <div class="now-grid">
        <div class="card now-main" id="home-fc"><div class="card-body"><div class="progress"></div></div></div>
        <div class="stack">
          <div class="card" id="home-where"><div class="card-body"><div class="progress"></div></div></div>
          <div class="card" id="home-season"><div class="card-body"><div class="progress"></div></div></div>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.tasks_t"))}</h2><p class="sub">${esc(t("home.tasks_s"))}</p>
      <div class="tasks">
        ${TASKS.map(([ic, i, href]) => `<a class="card task" href="${href}"><div class="ic">${icons[ic]}</div>
          <h3>${esc(t(`home.t${i}_t`))}</h3><p>${esc(t(`home.t${i}_d`))}</p>
          <span class="go">${esc(t(`home.t${i}_cta`))} ${icons.arrow}</span></a>`).join("")}
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.how_t"))}</h2><p class="sub">${esc(t("home.how_s"))}</p>
      <ol class="how-steps">
        ${STEPS.map(([ic, i]) => `<li class="card"><div class="top"><span class="num">${i}</span><span class="ic">${icons[ic]}</span></div>
          <h3>${esc(t(`home.h${i}_t`))}</h3><p>${esc(t(`home.h${i}_d`))}</p></li>`).join("")}
      </ol>
    </section>

    <section class="section">
      <h2>${esc(t("home.why_t"))}</h2><p class="sub">${esc(t("home.why_s"))}</p>
      <div class="card"><div class="card-body" style="padding-top:16px">
        <div id="why-legend"></div><div class="chart" id="why-chart"><div class="progress"></div></div>
        ${howTo(t("how.harm"))}
      </div></div>
    </section>

    <section class="section">
      <h2>${esc(t("home.aud_t"))}</h2><p class="sub">${esc(t("home.aud_s"))}</p>
      <div class="grid g2">
        ${[["tree", 1], ["cow", 2], ["lab", 3], ["bell", 4]].map(([ic, i]) => `<div class="card audience"><div class="ic">${icons[ic]}</div>
          <div><h4>${esc(t(`home.a${i}_t`))}</h4><p>${esc(t(`home.a${i}_d`))}</p></div></div>`).join("")}
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.faq_t"))}</h2><p class="sub">${esc(t("home.faq_s"))}</p>
      <div class="faq">
        ${t("home.faq").map(([q, a], i) => `<details class="card"${i === 0 ? " open" : ""}><summary>${icons.question}<span>${esc(q)}</span></summary><p>${esc(a)}</p></details>`).join("")}
      </div>
    </section>

    <section class="section">
      <h2>${esc(t("home.data_t"))}</h2><p class="sub">${esc(t("home.data_s"))}</p>
      ${dataStrip()}
      <div class="card card-pad" style="margin-top:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <span class="chip brand">${icons.sat}NOAA-20 · NOAA-21</span><span class="ink2">${esc(t("home.snpp"))}</span></div>
      ${partnersBlock()}
    </section>
    ${footer()}`;

  // ---------------------------------------------------------------- this week: forecast + where to act
  const fcBox = $("#home-fc", main), whereBox = $("#home-where", main), seasonBox = $("#home-season", main);
  api.get(`/api/forecast?lang=${getLang()}`).then((f) => {
    if (!fcBox.isConnected) return;
    const r = f.region.next2;
    const t2 = f.issue.targets?.[1];
    const until = t2 ? (() => { const d = new Date(t2.start + "T00:00:00"); d.setDate(d.getDate() + 6); return fmtDay(d.toISOString().slice(0, 10)); })() : null;
    fcBox.innerHTML = `<div class="card-head"><h3>${icons.spark} ${esc(t("home.fc_box"))}</h3>
        <span class="hint">${esc(t("fc.issued"))} ${esc(fmtDay(f.issue.week_end))}</span></div>
      <div class="card-body">
        <div class="now-risk">${riskChip(r.risk)}<b>${esc(t("fc.region"))}${until ? ` · ${esc(fr ? "jusqu'au" : "until")} ${esc(until)}` : ""}</b></div>
        <div class="mini-stats">
          <div><b>≈ ${about(r.mu)}</b><span>${esc(t("home.st_expected"))}</span></div>
          <div><b>×${fmt(r.ratio, 1)}</b><span>${esc(t("home.st_ratio"))}</span></div>
          <div><b>${r.prob_above != null ? fmt(100 * r.prob_above, 0) + (fr ? " %" : "%") : "–"}</b><span>${esc(t("home.st_prob"))}</span></div>
        </div>
        <div class="story">${forecastStory(inRegion(), r, f.region.next4, until).map((p) => `<p>${p}</p>`).join("")}</div>
        <div class="sms" style="margin-top:4px">${esc(f.region.message)}</div>
        <div class="row" style="justify-content:space-between;margin-top:8px">
          <span class="sms-meta">${esc(t("fc.sms_h"))}</span>
          <button class="btn sm" id="home-copy">${icons.copy}${esc(t("fc.copy"))}</button></div>
        <a class="btn primary" href="#/forecast" style="margin-top:14px">${icons.map}${esc(t("home.map_cta"))} →</a>
      </div>`;
    $("#home-copy", fcBox).addEventListener("click", async () => { if (await copyText(f.region.message)) toast(t("fc.copied")); });

    const order = { high: 0, moderate: 1, low: 2, offseason: 3 };
    const top = f.units.filter((u) => u.level === 2)
      .sort((a, b) => (order[a.next2.risk] - order[b.next2.risk]) || (b.next2.mu - a.next2.mu)).slice(0, 5);
    whereBox.innerHTML = `<div class="card-head"><h3>${icons.alert} ${esc(t("fc.where"))}</h3></div>
      <div class="card-body"><p class="small ink2" style="margin:0 0 8px">${esc(t("home.where_s"))}</p>
        <ol class="toplist">${top.map((u) => `<li><a href="#/forecast"><span class="nm"><b>${esc(u.name)}</b> <span class="muted small">${esc(u.parent || "")}</span></span>
          ${riskChip(u.next2.risk)}<span class="val">≈ ${about(u.next2.mu)} <span class="muted small">${esc(fr ? "feux" : "fires")}</span></span></a></li>`).join("")}</ol></div>`;
  }).catch(() => {
    if (fcBox.isConnected) fcBox.innerHTML = `<div class="card-body muted small">${esc(t("fc.unavailable"))}</div>`;
    if (whereBox.isConnected) whereBox.remove();
  });

  // ---------------------------------------------------------------- this week: current season
  api.get(`/api/season/overview?lang=${getLang()}`).then((d) => {
    if (!seasonBox.isConnected) return;
    if (!d.region) { seasonBox.remove(); return; }
    seasonBox.innerHTML = `<div class="card-head"><h3>${icons.calendar} ${esc(t("home.season_box"))}</h3>
        <div class="tools">${statusChip(d.region.cumulative_status)}</div></div>
      <div class="card-body"><div class="story">${seasonStory(d, { short: true }).map((p) => `<p>${p}</p>`).join("")}</div>
        <a class="btn" href="#/season">${esc(t("home.season_cta"))} →</a></div>`;
  }).catch(() => { if (seasonBox.isConnected) seasonBox.remove(); });

  // ---------------------------------------------------------------- why harmonise
  let data = null;
  const draw = () => {
    if (!data || !main.isConnected || !$("#why-chart", main)) return;
    const h = data.harmonized.filter((y) => y.complete && y.total != null);
    const n = data.naive.filter((y) => y.complete && y.total != null);
    const colH = cssVar("--brand"), colN = cssVar("--muted");
    const series = [
      { key: "n", label: t("home.naive"), short: fr ? "naïf" : "naive", color: colN, values: n.map((y) => ({ x: y.fyear, y: y.total })) },
      { key: "h", label: t("home.harm"), short: "FireSync", color: colH, values: h.map((y) => ({ x: y.fyear, y: y.total })) },
    ];
    charts.lines($("#why-chart", main), series, { height: 280,
      interval: { color: colH, values: h.map((y) => ({ x: y.fyear, lo: y.total_lo, hi: y.total_hi })) } });
    $("#why-legend", main).innerHTML = charts.legendHtml([...series, { label: t("home.interval"), color: colH + "44" }]);
  };
  api.get(`/api/region/summary?lang=${getLang()}`).then((d) => { data = d; draw(); })
    .catch((e) => { const el = $("#why-chart", main); if (el) el.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; });
  const onR = () => draw();
  window.addEventListener("fs-resize", onR);
  return () => window.removeEventListener("fs-resize", onR);
}
