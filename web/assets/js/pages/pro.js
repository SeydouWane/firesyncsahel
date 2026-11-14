import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, $$, esc, icons, toast, modal, confirmBox, fmt, fmtInt, fmtSigned, fmtDate, statusChip, loadingBlock, errorBlock, emptyBlock, riskChip, copyText, initials } from "../ui.js";
import { sparkline } from "../charts.js";
import { renderZone, sensorsChart } from "./zoneview.js";
import { FS } from "../main.js";

const CATS = ["departement", "foret_classee", "parcours", "aire_protegee", "autre"];

function head(main, title, sub, actions = "") {
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("space.pro"))}</div><h1>${esc(title)}</h1>
    <p class="sub">${esc(sub)}</p></div><div class="actions">${actions}</div></div><div id="body">${loadingBlock()}</div>`;
  return $("#body", main);
}

export async function render(main, ctx) {
  const pages = { dashboard, zones, analysis, bulletins, account };
  return pages[ctx.page](main, ctx);
}

async function dashboard(main) {
  const body = head(main, t("pro.dash_t"), t("pro.dash_s"), `<a class="btn primary" href="#/explorer">${icons.plus}${esc(t("pro.add_zone"))}</a>`);
  let rows;
  try { rows = await api.get(`/api/pro/dashboard?lang=${getLang()}`); } catch (e) { body.innerHTML = errorBlock(e); return; }
  if (!rows.length) {
    body.innerHTML = emptyBlock(icons.pin, t("pro.no_zones"), t("ex.empty_d"), `<a class="btn primary" href="#/explorer">${icons.map}${esc(t("pro.add_zone"))}</a>`);
    return;
  }
  const alerts = rows.filter((r) => r.alert).length;
  body.innerHTML = `
    <div class="kpis" style="margin-bottom:16px">
      <div class="kpi"><div class="label">${esc(t("nav.zones"))}</div><div class="value">${rows.length}</div></div>
      <div class="kpi ${alerts ? "hl" : ""}"><div class="label">${esc(t("pro.alert"))}</div><div class="value">${alerts}</div>
        <div class="note">${esc(t("pro.alert_pct"))}</div></div>
      <div class="kpi"><div class="label">${esc(t("ex.current"))}</div><div class="value" style="font-size:18px">${esc(rows[0].current || "–")}</div>
        <div class="note">${esc(t("common.data_to"))} ${esc(FS.meta?.last_date || "")}</div></div>
    </div>
    <div class="grid g3">${rows.map((r) => {
      const L = r.week_labels, last = r.last || {};
      return `<div class="card zone-card ${r.alert ? "alert" : ""}">
        <div class="row" style="justify-content:space-between"><h3>${esc(r.zone.name)}</h3>
          ${r.alert ? `<span class="chip crit">${icons.bell}${esc(t("pro.alert"))}</span>` : `<span class="chip">${esc(t("pro.cat." + (r.zone.category || "autre")))}</span>`}</div>
        <div class="meta">${statusChip(last.status)}<span class="small muted">${esc(t("ex.last_week"))} ${esc(L[last.fweek] || "–")}</span></div>
        <div class="row" style="justify-content:space-between;align-items:flex-end">
          <div><div class="small muted">${esc(t("ex.cum"))} ${esc(t("pro.since"))}</div><div class="strong" style="font-size:20px">${fmtInt(r.cumulative)}</div>
            <div class="small ink2">${esc(t("ex.pct"))} ${fmt(r.cumulative_pct, 0)} · ${statusChip(r.cumulative_status)}</div></div>
          <div title="${esc(t("ex.annual_t"))}">${sparkline(r.spark)}</div></div>
        ${r.forecast ? `<div class="sms" style="padding:10px 12px"><div class="row" style="gap:6px;margin-bottom:6px">${icons.spark}
            <b class="small">${esc(t("fc.next2"))}</b>${riskChip(r.forecast.next2.risk)}<span class="small muted">~${fmtInt(r.forecast.next2.mu)} · ×${fmt(r.forecast.next2.ratio, 1)}</span></div>
          <div class="small ink2">${esc(r.forecast.message)}</div>
          <button class="btn sm ghost" data-copy="${r.zone.id}" style="margin-top:6px">${icons.copy}${esc(t("fc.copy"))}</button></div>` : ""}
        <div class="row small ink2" style="gap:14px"><span>${esc(t("ex.onset"))} <b>${esc(L[r.summary.onset] || "–")}</b></span>
          <span>${esc(t("ex.peak"))} <b>${esc(L[r.summary.peak] || "–")}</b></span>
          <span>${esc(t("pro.trend"))} <b>${fmtSigned(r.trend, 0, " %")}</b></span></div>
        <div class="row"><a class="btn sm" href="#/pro/analysis/${r.zone.id}">${icons.chart}${esc(t("pro.analyse"))}</a></div>
      </div>`;
    }).join("")}</div>`;
  $$("[data-copy]", body).forEach((b) => b.addEventListener("click", async () => {
    const r = rows.find((x) => String(x.zone.id) === b.dataset.copy);
    if (r?.forecast && (await copyText(r.forecast.message))) toast(t("fc.copied"));
  }));
}

async function zoneForm(z = {}) {
  return modal(z.id ? t("common.edit") : t("pro.add_zone"), `
    <div class="field"><label for="zn">${esc(t("ex.zone_name"))}</label><input class="input" id="zn" value="${esc(z.name || "")}"></div>
    <div class="field"><label for="zc">${esc(t("pro.category"))}</label><select class="input" id="zc">
      ${CATS.map((c) => `<option value="${c}" ${z.category === c ? "selected" : ""}>${esc(t("pro.cat." + c))}</option>`).join("")}</select></div>
    <div class="field"><label for="za">${esc(t("pro.alert_pct"))}</label><input class="input" id="za" type="number" min="50" max="100" value="${z.alert_pct ?? 90}"></div>
    <div class="field"><label for="zt">${esc(t("pro.notes"))}</label><textarea class="input" id="zt">${esc(z.notes || "")}</textarea></div>`, {
    actions: [{ label: t("common.cancel"), value: null }, { label: t("common.save"), primary: true,
      value: (b) => ({ name: b.querySelector("#zn").value, category: b.querySelector("#zc").value,
        alert_pct: +b.querySelector("#za").value, notes: b.querySelector("#zt").value }) }],
  });
}

async function zones(main) {
  const body = head(main, t("pro.zones_t"), t("pro.zones_s"), `<a class="btn primary" href="#/explorer">${icons.plus}${esc(t("pro.add_zone"))}</a>`);
  const load = async () => {
    const list = await api.get("/api/pro/zones");
    if (!list.length) { body.innerHTML = emptyBlock(icons.pin, t("pro.no_zones"), t("ex.empty_d")); return; }
    body.innerHTML = `<div class="card"><div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("common.name"))}</th><th>${esc(t("pro.category"))}</th>
      <th class="num">${esc(t("pro.alert_pct"))}</th><th>${esc(t("pro.notes"))}</th><th>${esc(t("common.created"))}</th><th></th></tr></thead><tbody>
      ${list.map((z) => `<tr><td class="strong">${esc(z.name)}</td><td>${esc(t("pro.cat." + (z.category || "autre")))}</td><td class="num">${z.alert_pct ?? "–"}</td>
        <td class="small ink2">${esc(z.notes || "")}</td><td class="small">${esc(fmtDate(z.created_at))}</td>
        <td><div class="row" style="flex-wrap:nowrap;justify-content:flex-end"><a class="btn sm" href="#/pro/analysis/${z.id}">${esc(t("pro.analyse"))}</a>
          <button class="btn sm ghost" data-edit="${z.id}">${esc(t("common.edit"))}</button>
          <button class="btn sm danger" data-del="${z.id}">${esc(t("common.delete"))}</button></div></td></tr>`).join("")}
      </tbody></table></div></div>`;
    $$("[data-edit]", body).forEach((b) => b.addEventListener("click", async () => {
      const z = list.find((x) => x.id === +b.dataset.edit);
      const v = await zoneForm(z);
      if (!v) return;
      try { await api.put(`/api/pro/zones/${z.id}`, { ...v, geometry: z.geometry }); toast(t("common.save")); load(); } catch (e) { toast(e.message, true); }
    }));
    $$("[data-del]", body).forEach((b) => b.addEventListener("click", async () => {
      if (!(await confirmBox(`${t("common.delete")} ?`))) return;
      try { await api.del(`/api/pro/zones/${b.dataset.del}`); load(); } catch (e) { toast(e.message, true); }
    }));
  };
  try { await load(); } catch (e) { body.innerHTML = errorBlock(e); }
}

async function analysis(main, { param }) {
  const body = head(main, t("pro.analysis_t"), "", "");
  const actions = $(".page-head .actions", main);
  let list;
  try { list = await api.get("/api/pro/zones"); } catch (e) { body.innerHTML = errorBlock(e); return; }
  if (!body.isConnected) return;
  if (!list.length) { body.innerHTML = emptyBlock(icons.chart, t("pro.no_zones"), t("ex.empty_d"), `<a class="btn primary" href="#/explorer">${esc(t("pro.add_zone"))}</a>`); return; }
  const zone = list.find((z) => String(z.id) === String(param)) || list[0];
  actions.innerHTML = `<select class="input" id="zsel" style="min-width:220px">${list.map((z) => `<option value="${z.id}" ${z.id === zone.id ? "selected" : ""}>${esc(z.name)}</option>`).join("")}</select>`;
  $("#zsel", main).addEventListener("change", (e) => { location.hash = `#/pro/analysis/${e.target.value}`; });
  const st = { mode: "harmonized", start: "auto" };
  let cleanup = null;
  const q = () => ({ geometry: zone.geometry, name: zone.name, mode: st.mode, start_week: st.start, lang: getLang() });
  const run = async () => {
    body.innerHTML = loadingBlock(t("ex.computing"));
    try {
      const res = await api.post("/api/zone/calendar", q());
      body.innerHTML = `<div id="zv"></div>
        <div class="grid g2" style="margin-top:16px">
          <div class="card"><div class="card-head"><h3>${esc(t("ex.sensors_t"))}</h3></div><div class="card-body"><div id="sens-leg"></div><div class="chart" id="c-sens"></div></div></div>
          <div class="card"><div class="card-head"><h3>${esc(t("pro.exports"))}</h3></div><div class="card-body stack" style="gap:10px">
            <button class="btn" data-x="csv">${icons.download}${esc(t("pro.csv"))}</button>
            <button class="btn" data-x="geojson">${icons.download}${esc(t("pro.geojson"))}</button>
            <button class="btn" data-x="pdf-fr">${icons.doc}${esc(t("pro.pdf_fr"))}</button>
            <button class="btn" data-x="pdf-en">${icons.doc}${esc(t("pro.pdf_en"))}</button>
            <p class="small muted">${esc(t("common.unit"))}</p></div></div>
        </div>`;
      if (cleanup) cleanup();
      cleanup = renderZone($("#zv", body), res, { mode: st.mode, startWeek: st.start, geometry: zone.geometry,
        onMode: (m) => { st.mode = m; run(); }, onStart: (s) => { st.start = s; run(); } });
      $("#sens-leg", body).innerHTML = sensorsChart($("#c-sens", body), res);
      $$("[data-x]", body).forEach((b) => b.addEventListener("click", async () => {
        const x = b.dataset.x; b.disabled = true;
        try {
          if (x === "csv") await api.download("/api/pro/export/csv", q(), "series.csv");
          else if (x === "geojson") await api.download("/api/pro/export/geojson", q(), "zone.geojson");
          else await api.download("/api/zone/bulletin", { ...q(), lang: x.slice(4) }, "bulletin.pdf");
        } catch (e) { toast(e.message, true); }
        b.disabled = false;
      }));
    } catch (e) { body.innerHTML = errorBlock(e); }
  };
  run();
  return () => cleanup && cleanup();
}

async function bulletins(main) {
  const body = head(main, t("pro.bull_t"), t("pro.bull_s"));
  let list;
  try { list = await api.get("/api/pro/zones"); } catch (e) { body.innerHTML = errorBlock(e); return; }
  if (!list.length) { body.innerHTML = emptyBlock(icons.doc, t("pro.no_zones"), t("ex.empty_d")); return; }
  body.innerHTML = `<div class="card"><div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("common.name"))}</th><th>${esc(t("pro.category"))}</th><th></th></tr></thead><tbody>
    ${list.map((z) => `<tr><td class="strong">${esc(z.name)}</td><td>${esc(t("pro.cat." + (z.category || "autre")))}</td>
      <td><div class="row" style="justify-content:flex-end;flex-wrap:nowrap"><button class="btn sm" data-b="${z.id}" data-l="fr">${icons.doc}FR</button>
      <button class="btn sm" data-b="${z.id}" data-l="en">${icons.doc}EN</button></div></td></tr>`).join("")}</tbody></table></div></div>`;
  $$("[data-b]", body).forEach((b) => b.addEventListener("click", async () => {
    const z = list.find((x) => x.id === +b.dataset.b); b.disabled = true;
    const old = b.innerHTML; b.innerHTML = `<span class="spinner"></span>`;
    try { await api.download("/api/zone/bulletin", { geometry: z.geometry, name: z.name, lang: b.dataset.l }, "bulletin.pdf"); }
    catch (e) { toast(e.message, true); }
    b.disabled = false; b.innerHTML = old;
  }));
}

async function account(main) {
  const u = FS.user;
  const body = head(main, t("pro.account_t"), u.email);
  body.innerHTML = `<div class="grid g2">
    <div class="card card-pad"><div class="row"><span class="avatar" style="width:52px;height:52px;font-size:18px">${esc(initials(u))}</span>
      <div><h3 style="font-size:17px">${esc(u.name || u.email)}</h3><div class="small ink2">${esc(u.email)} · ${esc(u.org || "")}</div>
      <div style="margin-top:6px"><span class="chip brand">${esc(t("common." + u.role))}</span></div></div></div>
      <hr class="divider"><div class="small ink2">${esc(t("common.last_login"))} : ${esc(fmtDate(u.last_login))}</div></div>
    <form class="card card-pad" id="pw"><h3 style="font-size:16px;margin-bottom:12px">${esc(t("pro.pw_t"))}</h3>
      <div class="field"><label for="p1">${esc(t("pro.pw_cur"))}</label><input class="input" id="p1" type="password" required autocomplete="current-password"></div>
      <div class="field"><label for="p2">${esc(t("pro.pw_new"))}</label><input class="input" id="p2" type="password" minlength="8" required autocomplete="new-password"></div>
      <button class="btn primary" type="submit">${esc(t("common.save"))}</button></form></div>`;
  $("#pw", body).addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api.post("/api/auth/password", { current: $("#p1").value, new: $("#p2").value }); toast(t("pro.pw_ok")); e.target.reset(); }
    catch (err) { toast(err.message, true); }
  });
}
