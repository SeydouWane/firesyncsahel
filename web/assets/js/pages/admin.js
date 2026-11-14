import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, $$, esc, icons, toast, modal, confirmBox, fmt, fmtInt, fmtDate, fmtDay, loadingBlock, errorBlock } from "../ui.js";
import * as charts from "../charts.js";
import { refreshBadges, rerender, FS } from "../main.js";

function head(main, title, sub, actions = "") {
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("space.admin"))}</div><h1>${esc(title)}</h1>
    <p class="sub">${esc(sub)}</p></div><div class="actions">${actions}</div></div><div id="body">${loadingBlock()}</div>`;
  return $("#body", main);
}

export async function render(main, ctx) {
  return { overview, pipeline, users, refzones, settings, audit }[ctx.page](main, ctx);
}

async function overview(main) {
  const body = head(main, t("adm.ov_t"), t("adm.ov_s"));
  let d;
  try { d = await api.get("/api/admin/overview"); } catch (e) { body.innerHTML = errorBlock(e); return; }
  refreshBadges(d.counts.requests);
  const m = d.model, st = d.step_test || {};
  body.innerHTML = `
    <div class="kpis">
      <div class="kpi"><div class="label">${esc(t("adm.users_n"))}</div><div class="value">${d.counts.users}</div><div class="note">${d.counts.pros} ${esc(t("adm.pros_n"))}</div></div>
      <div class="kpi"><div class="label">${esc(t("adm.zones_n"))}</div><div class="value">${d.counts.zones}</div><div class="note">${d.counts.reference} ${esc(t("adm.ref_n"))}</div></div>
      <div class="kpi ${d.counts.requests ? "hl" : ""}"><div class="label">${esc(t("adm.req_n"))}</div><div class="value">${d.counts.requests}</div>
        <div class="note"><a href="#/admin/users">${esc(t("nav.users"))}</a></div></div>
      <div class="kpi"><div class="label">${esc(t("common.data_to"))}</div><div class="value" style="font-size:18px">${esc(fmtDay(d.last_date))}</div>
        <div class="note">${d.raw_files} CSV · ${fmt(d.raw_mb, 0)} Mo</div></div>
      <div class="kpi"><div class="label">${esc(t("adm.step"))}</div><div class="value">×${fmt(st.step_harmonised, 2)}</div>
        <div class="note">${esc(t("home.naive"))} ×${fmt(st.step_naive, 2)}</div></div>
    </div>
    ${d.nrt.configured ? "" : `<div class="status-banner warn" style="margin-top:16px"><div class="status-icon" style="background:#b77d00">!</div>
      <div><div class="strong">${esc(t("adm.nrt_t"))}</div><div class="small ink2">${esc(t("adm.nrt_missing"))} <a href="#/admin/settings">${esc(t("nav.settings"))}</a></div></div></div>`}
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>${esc(t("adm.per_year"))}</h3></div><div class="card-body"><div id="l-sy"></div><div class="chart" id="c-sy"></div></div></div>
      <div class="card"><div class="card-head"><h3>${esc(t("adm.coverage"))}</h3></div><div class="card-body"><div class="table-wrap"><table class="table">
        <thead><tr><th></th><th>${esc(t("adm.first"))}</th><th>${esc(t("adm.last"))}</th><th class="num">${esc(t("adm.count"))}</th></tr></thead>
        <tbody>${d.coverage.map((c) => `<tr><td>${esc(c.sensor)}</td><td>${esc(c.first)}</td><td>${esc(c.last)}</td><td class="num">${fmtInt(c.n)}</td></tr>`).join("")}</tbody></table></div>
        <hr class="divider"><h3 style="font-size:15px;margin-bottom:8px">${esc(t("adm.model_t"))}</h3>
        <div class="small ink2" style="display:grid;gap:4px">
          <div>${esc(t("adm.generated"))} : <b>${esc(m.generated || "–")}</b> (${fmt(m.seconds, 0)} s)</div>
          <div>${esc(t("adm.train"))} : <b>${(m.train_fire_years || []).join(", ")}</b></div>
          <div>${esc(t("adm.members"))} : <b>${m.members}</b> · ${esc(t("method.lc_used"))} : <b>${esc(m.land_cover?.product || "–")}</b></div>
          <div>${esc(t("adm.kappa"))} : ${Object.entries(m.kappa || {}).map(([k, v]) => `${esc(k)} <b>${fmt(v, 2)}</b>`).join(" · ")}</div>
        </div></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("adm.jobs_t"))}</h3><div class="tools"><a class="btn sm" href="#/admin/pipeline">${esc(t("nav.pipeline"))}</a></div></div>
      <div class="card-body">${jobsTable(d.jobs)}</div></div>`;
  const draw = () => { $("#l-sy", body).innerHTML = charts.sensorYears($("#c-sy", body), d.per_year); };
  draw();
  const onR = () => draw();
  window.addEventListener("fs-resize", onR);
  return () => window.removeEventListener("fs-resize", onR);
}

function jobsTable(jobs) {
  if (!jobs.length) return `<p class="muted small">–</p>`;
  const cls = { running: "warn", done: "ok", failed: "crit" };
  return `<div class="table-wrap"><table class="table"><thead><tr><th>#</th><th>Job</th><th>${esc(t("common.status"))}</th><th>Start</th><th>End</th><th></th></tr></thead><tbody>
    ${jobs.map((j) => `<tr><td>${j.id}</td><td>${esc(t("adm.job." + j.kind))}</td><td><span class="chip ${cls[j.status] || ""}">${esc(t("adm." + j.status))}</span></td>
      <td class="small">${esc(fmtDate(j.started_at))}</td><td class="small">${esc(fmtDate(j.finished_at))}</td>
      <td>${j.log !== undefined ? `<button class="btn sm ghost" data-log="${j.id}">Log</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
}

async function pipeline(main) {
  const body = head(main, t("adm.pipe_t"), t("adm.pipe_s"));
  const kinds = ["refresh", "forecast", "download", "nrt", "process", "boundaries", "landcover", "burned", "validate", "fit", "reload"];
  const icon = { refresh: "sat", forecast: "spark", download: "download", nrt: "sat", process: "cpu", boundaries: "map", landcover: "tree", burned: "flame", validate: "method", fit: "cpu", reload: "layers" };
  const sl = !!FS.meta?.serverless;
  body.innerHTML = `${sl ? `<div class="card card-pad" style="margin-bottom:16px;border-color:var(--brand)"><b>${esc(t("adm.serverless_t"))}</b>
      <p class="small ink2" style="margin:6px 0 0">${esc(t("adm.serverless_d"))}</p></div>` : ""}
    <div class="grid g3">${kinds.map((k) => `<div class="card card-pad" style="display:flex;flex-direction:column;gap:10px">
      <div class="row"><span class="status-icon" style="background:var(--brand-soft);color:var(--brand);width:36px;height:36px">${icons[icon[k]]}</span>
      <b>${esc(t("adm.job." + k))}</b></div><button class="btn sm primary" data-run="${k}" style="align-self:flex-start" ${sl && k !== "reload" ? "disabled" : ""}>${esc(t("adm.run"))}</button></div>`).join("")}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("adm.jobs_t"))}</h3></div><div class="card-body" id="jobs"></div></div>
    <div class="card" style="margin-top:16px" id="logcard" hidden><div class="card-head"><h3 id="logtitle">Log</h3></div><div class="card-body"><pre class="log" id="log"></pre></div></div>`;
  let timer = null, watch = null;
  const refresh = async () => {
    const jobs = await api.get("/api/admin/jobs");
    $("#jobs", body).innerHTML = jobsTable(jobs);
    $$("[data-log]", body).forEach((b) => b.addEventListener("click", () => { watch = +b.dataset.log; refresh(); }));
    const j = jobs.find((x) => x.id === watch) || (jobs[0]?.status === "running" ? jobs[0] : null);
    if (j) {
      $("#logcard", body).hidden = false;
      $("#logtitle", body).textContent = `#${j.id} · ${t("adm.job." + j.kind)} · ${t("adm." + j.status)}`;
      const pre = $("#log", body); const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
      pre.textContent = j.log || "…"; if (atEnd) pre.scrollTop = pre.scrollHeight;
    }
    const busy = jobs.some((x) => x.status === "running");
    $$("[data-run]", body).forEach((b) => (b.disabled = busy || (sl && b.dataset.run !== "reload")));
    clearTimeout(timer);
    if (jobs.some((x) => x.status === "running")) timer = setTimeout(refresh, 2500);
  };
  $$("[data-run]", body).forEach((b) => b.addEventListener("click", async () => {
    if (["download", "validate", "fit", "burned"].includes(b.dataset.run) && !(await confirmBox(t("adm.job." + b.dataset.run) + " ?"))) return;
    try { const r = await api.post(`/api/admin/jobs/${b.dataset.run}`); watch = r.id; refresh(); } catch (e) { toast(e.message, true); }
  }));
  refresh();
  return () => clearTimeout(timer);
}

async function users(main) {
  const body = head(main, t("adm.users_t"), t("adm.users_s"), `<button class="btn primary" id="new-user">${icons.plus}${esc(t("adm.new_user"))}</button>`);
  const showPw = (pw) => modal(t("adm.new_user"), `<p class="small ink2">${esc(t("adm.gen_pw"))}</p><div class="secret">${esc(pw)}</div>`);
  const load = async () => {
    const [list, reqs] = await Promise.all([api.get("/api/admin/users"), api.get("/api/admin/requests")]);
    const pending = reqs.filter((r) => r.status === "pending");
    refreshBadges(pending.length);
    body.innerHTML = `
      <div class="card"><div class="card-head"><h3>${esc(t("adm.requests"))}</h3><span class="chip ${pending.length ? "warn" : ""}">${pending.length}</span></div>
        <div class="card-body">${reqs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("common.name"))}</th><th>${esc(t("common.email"))}</th>
          <th>${esc(t("common.org"))}</th><th>${esc(t("about.profile"))}</th><th>${esc(t("about.message"))}</th><th>${esc(t("common.status"))}</th><th></th></tr></thead><tbody>
          ${reqs.map((r) => `<tr><td class="strong">${esc(r.name)}</td><td>${esc(r.email)}</td><td>${esc(r.org)}</td><td class="small">${esc(r.profile)}</td>
            <td class="small ink2" style="max-width:280px">${esc(r.message)}</td><td><span class="chip ${r.status === "pending" ? "warn" : r.status === "approved" ? "ok" : ""}">${esc(r.status)}</span></td>
            <td>${r.status === "pending" ? `<div class="row" style="flex-wrap:nowrap"><button class="btn sm primary" data-req="${r.id}" data-a="approve">${esc(t("adm.approve"))}</button>
              <button class="btn sm ghost" data-req="${r.id}" data-a="reject">${esc(t("adm.reject"))}</button></div>` : ""}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="muted small">–</p>`}</div></div>
      <div class="card" style="margin-top:16px"><div class="card-head"><h3>${esc(t("adm.users_n"))}</h3></div><div class="card-body"><div class="table-wrap"><table class="table">
        <thead><tr><th>${esc(t("common.name"))}</th><th>${esc(t("common.email"))}</th><th>${esc(t("common.org"))}</th><th>${esc(t("common.role"))}</th>
          <th>${esc(t("common.status"))}</th><th>${esc(t("common.last_login"))}</th><th></th></tr></thead><tbody>
        ${list.map((u) => `<tr><td class="strong">${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.org)}</td>
          <td><select class="input" data-role="${u.id}" style="min-height:32px;padding:3px 8px;width:auto" ${u.id === FS.user.id ? "disabled" : ""}>
            <option value="pro" ${u.role === "pro" ? "selected" : ""}>${esc(t("common.pro"))}</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>${esc(t("common.admin"))}</option></select></td>
          <td><span class="chip ${u.active ? "ok" : ""}">${esc(u.active ? t("common.active") : t("common.disabled"))}</span></td>
          <td class="small">${esc(fmtDate(u.last_login))}</td>
          <td><div class="row" style="flex-wrap:nowrap;justify-content:flex-end">${u.id === FS.user.id ? "" : `
            <button class="btn sm ghost" data-toggle="${u.id}" data-active="${u.active}">${esc(u.active ? t("common.disabled") : t("common.active"))}</button>
            <button class="btn sm ghost" data-reset="${u.id}">${esc(t("adm.reset"))}</button>
            <button class="btn sm danger" data-del="${u.id}">${esc(t("common.delete"))}</button>`}</div></td></tr>`).join("")}
        </tbody></table></div></div></div>`;
    $$("[data-req]", body).forEach((b) => b.addEventListener("click", async () => {
      try { const r = await api.post(`/api/admin/requests/${b.dataset.req}/${b.dataset.a}`); if (r.password) await showPw(r.password); load(); }
      catch (e) { toast(e.message, true); }
    }));
    $$("[data-role]", body).forEach((s) => s.addEventListener("change", async () => {
      try { await api.patch(`/api/admin/users/${s.dataset.role}`, { role: s.value }); toast(t("common.save")); } catch (e) { toast(e.message, true); load(); }
    }));
    $$("[data-toggle]", body).forEach((b) => b.addEventListener("click", async () => {
      try { await api.patch(`/api/admin/users/${b.dataset.toggle}`, { active: b.dataset.active !== "1" }); load(); } catch (e) { toast(e.message, true); }
    }));
    $$("[data-reset]", body).forEach((b) => b.addEventListener("click", async () => {
      if (!(await confirmBox(t("adm.reset") + " ?"))) return;
      try { const r = await api.post(`/api/admin/users/${b.dataset.reset}/reset-password`); await showPw(r.password); } catch (e) { toast(e.message, true); }
    }));
    $$("[data-del]", body).forEach((b) => b.addEventListener("click", async () => {
      if (!(await confirmBox(t("common.delete") + " ?"))) return;
      try { await api.del(`/api/admin/users/${b.dataset.del}`); load(); } catch (e) { toast(e.message, true); }
    }));
  };
  $("#new-user", main).addEventListener("click", async () => {
    const v = await modal(t("adm.new_user"), `
      <div class="field"><label for="ue">${esc(t("common.email"))}</label><input class="input" id="ue" type="email" required></div>
      <div class="field"><label for="un">${esc(t("common.name"))}</label><input class="input" id="un"></div>
      <div class="field"><label for="uo">${esc(t("common.org"))}</label><input class="input" id="uo"></div>
      <div class="field"><label for="ur">${esc(t("common.role"))}</label><select class="input" id="ur"><option value="pro">${esc(t("common.pro"))}</option><option value="admin">${esc(t("common.admin"))}</option></select></div>`, {
      actions: [{ label: t("common.cancel"), value: null }, { label: t("common.create"), primary: true,
        value: (b) => ({ email: b.querySelector("#ue").value, name: b.querySelector("#un").value, org: b.querySelector("#uo").value, role: b.querySelector("#ur").value }) }],
    });
    if (!v || !v.email) return;
    try { const r = await api.post("/api/admin/users", v); if (r.password) await showPw(r.password); load(); } catch (e) { toast(e.message, true); }
  });
  try { await load(); } catch (e) { body.innerHTML = errorBlock(e); }
}

async function refzones(main) {
  const body = head(main, t("adm.ref_t"), t("adm.ref_s"));
  const cats = ["foret_classee", "parcours", "aire_protegee", "departement", "autre"];
  const load = async () => {
    const gj = await api.get("/api/reference-zones");
    body.innerHTML = `<div class="grid g2">
      <form class="card card-pad" id="up"><h3 style="font-size:16px;margin-bottom:12px">${esc(t("adm.ref_upload"))}</h3>
        <div class="field"><label for="rn">${esc(t("adm.ref_name"))}</label><input class="input" id="rn" required></div>
        <div class="field"><label for="rc">${esc(t("pro.category"))}</label><select class="input" id="rc">${cats.map((c) => `<option value="${c}">${esc(t("pro.cat." + c))}</option>`).join("")}</select></div>
        <div class="field"><label for="rf">GeoJSON</label><input class="input" id="rf" type="file" accept=".geojson,.json" required></div>
        <button class="btn primary" type="submit">${icons.upload}${esc(t("common.save"))}</button></form>
      <div class="card"><div class="card-head"><h3>${esc(t("adm.ref_n"))}</h3><span class="chip">${gj.features.length}</span></div><div class="card-body">
        ${gj.features.length ? `<div class="table-wrap"><table class="table"><tbody>${gj.features.map((f) => `<tr><td class="strong">${esc(f.properties.name)}</td>
          <td class="small">${esc(t("pro.cat." + f.properties.category))}</td><td><button class="btn sm danger" data-del="${f.properties.id}">${esc(t("common.delete"))}</button></td></tr>`).join("")}
          </tbody></table></div>` : `<p class="muted small">${esc(t("ex.no_ref"))}</p>`}</div></div></div>`;
    $("#up", body).addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const gjf = JSON.parse(await $("#rf", body).files[0].text());
        const r = await api.post("/api/admin/reference-zones", { name: $("#rn", body).value, category: $("#rc", body).value, geojson: gjf });
        toast(`${r.created} ✓`); load();
      } catch (err) { toast(err.message, true); }
    });
    $$("[data-del]", body).forEach((b) => b.addEventListener("click", async () => {
      if (!(await confirmBox(t("common.delete") + " ?"))) return;
      await api.del(`/api/admin/reference-zones/${b.dataset.del}`); load();
    }));
  };
  try { await load(); } catch (e) { body.innerHTML = errorBlock(e); }
}

async function settings(main) {
  const body = head(main, t("adm.set_t"), t("adm.set_s"));
  let s, nrt;
  try { [s, nrt] = await Promise.all([api.get("/api/admin/settings"), api.get("/api/admin/nrt-status").catch(() => ({}))]); }
  catch (e) { body.innerHTML = errorBlock(e); return; }
  const partners = (s.partners || []).map((p) => [p.name, p.url || "", p.logo || "", p.role || "partner", p.dark ? "dark" : ""].join(" | ").replace(/[ |]+$/, "")).join("\n");
  const logoPreview = (s.partners || []).filter((p) => p.logo).map((p) => `<span class="logo-tile${p.dark ? " dark" : ""}" title="${esc(p.name)}"><img src="${esc(p.logo)}" alt="${esc(p.name)}"></span>`).join("");
  body.innerHTML = `<form class="card card-pad" id="sf" style="max-width:820px">
    <div class="field"><label for="mk">${esc(t("adm.map_key"))}</label><input class="input" id="mk" placeholder="${esc(s.firms_map_key || "")}" autocomplete="off">
      <span class="help">${esc(t("adm.map_key_h"))} ${s.firms_map_key_source ? `· <b>${esc(s.firms_map_key_source)}</b>` : ""}
      ${nrt.configured ? (nrt.error ? ` · ${esc(nrt.error)}` : ` · ${esc(JSON.stringify(nrt).slice(0, 160))}`) : ""}</span></div>
    <label class="row" style="margin-bottom:14px"><input type="checkbox" id="pb" ${s.public_bulletins !== false ? "checked" : ""}> ${esc(t("adm.public_bull"))}</label>
    <div class="field"><label for="pa">${esc(t("adm.partners"))}</label>
      ${logoPreview ? `<div class="partner-row" style="margin-bottom:8px">${logoPreview}</div>` : ""}
      <textarea class="input" id="pa" rows="5" placeholder="Organisation | https://… | /assets/partners/logo.png | partner | dark">${esc(partners)}</textarea>
      <span class="help">${esc(t("adm.partners_h"))}</span></div>
    <button class="btn primary" type="submit">${esc(t("common.save"))}</button></form>`;
  $("#sf", body).addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = { public_bulletins: $("#pb").checked,
      partners: $("#pa").value.split("\n").map((l) => l.split("|").map((x) => x.trim())).filter((p) => p[0])
        .map(([name, url, logo, role, dark]) => ({ name, url: url || "", logo: logo || "", role: role || "partner", dark: /^(dark|sombre|oui|yes|1)$/i.test(dark || "") })) };
    if ($("#mk").value.trim()) payload.firms_map_key = $("#mk").value.trim();
    try { await api.put("/api/admin/settings", payload); toast(t("common.save")); FS.meta = await api.get("/api/meta"); rerender(); } catch (err) { toast(err.message, true); }
  });
}

async function audit(main) {
  const body = head(main, t("adm.audit_t"), t("adm.audit_s"));
  try {
    const rows = await api.get("/api/admin/audit?limit=300");
    body.innerHTML = `<div class="card"><div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("adm.when"))}</th><th>${esc(t("adm.who"))}</th>
      <th>${esc(t("adm.what"))}</th><th>${esc(t("adm.detail"))}</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="small" style="white-space:nowrap">${esc(fmtDate(r.ts))}</td><td>${esc(r.email || "—")}</td><td><span class="chip">${esc(r.action)}</span></td>
        <td class="small ink2">${esc(r.detail)}</td></tr>`).join("")}</tbody></table></div></div>`;
  } catch (e) { body.innerHTML = errorBlock(e); }
}
