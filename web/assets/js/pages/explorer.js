import { api } from "../api.js";
import { t, getLang } from "../i18n.js";
import { $, $$, esc, toast, icons, loadingBlock, errorBlock, emptyBlock, modal, fmtInt } from "../ui.js";
import { FireMap, hexLegend } from "../map.js";
import { renderZone } from "./zoneview.js";
import { FS } from "../main.js";

const state = { zone: null, mode: "harmonized", start: "auto", tab: "admin", level: 2, layer: "density" };
let adminCache = {};

export async function render(main, { query }) {
  main.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">${esc(t("space.public"))}</div><h1>${esc(t("ex.title"))}</h1>
      <p class="sub">${esc(t("ex.sub"))}</p></div></div>
    <div class="explorer">
      <div class="card card-pad zone-picker">
        <div class="tabs" role="tablist">
          ${["admin", "draw", "upload", "ref"].map((k) => `<button role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${esc(t("ex.tab_" + k))}</button>`).join("")}
        </div>
        <div id="tab-body"></div>
      </div>
      <div class="map-wrap"><div class="map" id="map"></div>
        <div class="map-tools"><div class="map-panel">
          <label class="small strong muted" for="layer">${esc(t("ex.map_layer"))}</label>
          <select class="input" id="layer" style="min-height:34px;margin-top:4px;padding:4px 8px">
            <option value="density">${esc(t("ex.layer_density"))}</option>
            <option value="trend">${esc(t("ex.layer_trend"))}</option>
            <option value="anomaly">${esc(t("ex.layer_anomaly"))}</option>
            <option value="points">${esc(t("ex.layer_points"))}</option>
            <option value="none">—</option>
          </select></div></div>
        <div id="legend-slot"></div>
        <div class="draw-hint" id="draw-hint" hidden></div>
      </div>
    </div>
    <div id="results" style="margin-top:22px"></div>`;

  const fm = new FireMap($("#map", main));
  const meta = FS.meta;
  const lastFy = meta ? (meta.start_week != null ? (() => {
    const d = new Date(meta.last_date); const wk = Math.min(51, Math.floor((d - new Date(d.getFullYear(), 0, 1)) / 864e5 / 7));
    return wk >= meta.start_week ? d.getFullYear() : d.getFullYear() - 1;
  })() : null) : null;

  async function setLayer(kind) {
    state.layer = kind;
    $("#legend-slot", main).innerHTML = "";
    fm.clearPoints();
    if (kind === "none") { fm.showHex(false); return; }
    if (kind === "points") {
      fm.showHex(false);
      try {
        const pts = await api.get(`/api/map/points?fyear=${lastFy - 1}`);
        await fm.setPoints(pts);
        $("#legend-slot", main).innerHTML = `<div class="map-panel map-legend small"><b>${fmtInt(pts.n)} ${esc(t("common.detections"))}</b> · ${lastFy - 1}-${String(lastFy).slice(2)}
          <div class="legend" style="margin:6px 0 0"><span><i class="sw" style="background:#eb6834"></i>Terra</span><span><i class="sw" style="background:#eda100"></i>Aqua</span>
          <span><i class="sw" style="background:#2a78d6"></i>S-NPP</span><span><i class="sw" style="background:#1baf7a"></i>NOAA-20</span></div></div>`;
      } catch (e) { toast(e.message, true); }
      return;
    }
    try {
      const q = kind === "anomaly" ? `metric=anomaly&fyear=${lastFy - 1}` : `metric=${kind}`;
      const gj = await api.get(`/api/map/hex?${q}`);
      const info = await fm.setHex(gj, kind);
      fm.showHex(true);
      $("#legend-slot", main).innerHTML = hexLegend(info);
    } catch (e) { toast(e.message, true); }
  }
  $("#layer", main).value = state.layer;
  $("#layer", main).addEventListener("change", (e) => setLayer(e.target.value));
  setLayer(state.layer);

  async function loadAdmin(level) {
    if (!adminCache[level]) adminCache[level] = await api.get(`/api/admin-units?level=${level}`);
    return adminCache[level];
  }
  loadAdmin(2).then((gj) => fm.setAdmin(gj, (f) => selectAdmin(f))).catch(() => {});

  function selectAdmin(f) {
    const p = f.properties;
    const gj = adminCache[p.level]?.features.find((x) => x.properties.id === p.id) || f;
    compute({ name: p.parent ? `${p.name} (${p.parent})` : p.name, geometry: gj.geometry, kind: "admin" });
    $$(".list button", main).forEach((b) => b.classList.toggle("active", b.dataset.id === p.id));
  }

  async function renderTab() {
    $$(".tabs button", main).forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
    const body = $("#tab-body", main);
    fm.stopDraw(); $("#draw-hint", main).hidden = true;
    if (state.tab === "admin") {
      body.innerHTML = `<div class="seg" style="margin-bottom:10px"><button data-level="1" aria-pressed="${state.level === 1}">${esc(t("ex.level1"))}</button>
        <button data-level="2" aria-pressed="${state.level === 2}">${esc(t("ex.level2"))}</button></div>
        <input class="input" id="admin-filter" placeholder="${esc(t("ex.filter"))}" style="margin-bottom:10px">
        <div class="list" id="admin-list"><div class="card-pad"><div class="spinner"></div></div></div>`;
      $$("[data-level]", body).forEach((b) => b.addEventListener("click", () => { state.level = +b.dataset.level; renderTab(); }));
      const gj = await loadAdmin(state.level);
      fm.setAdmin(gj, (f) => selectAdmin(f));
      const feats = [...gj.features].sort((a, b) => a.properties.name.localeCompare(b.properties.name, "fr"));
      const draw = (q = "") => {
        const ql = q.toLowerCase();
        $("#admin-list", body).innerHTML = feats.filter((f) => !ql || f.properties.name.toLowerCase().includes(ql) || (f.properties.parent || "").toLowerCase().includes(ql))
          .map((f) => `<button data-id="${esc(f.properties.id)}"><span>${esc(f.properties.name)}</span><span class="muted small">${esc(f.properties.parent || f.properties.iso3)}</span></button>`).join("");
        $$("#admin-list button", body).forEach((b) => b.addEventListener("click", () => selectAdmin(feats.find((f) => f.properties.id === b.dataset.id))));
      };
      draw($("#admin-filter", body).value);  // keep what was typed while the list was loading
      $("#admin-filter", body).addEventListener("input", (e) => draw(e.target.value));
    } else if (state.tab === "draw") {
      body.innerHTML = `<p class="ink2 small">${esc(t("ex.draw_hint"))}</p>
        <div class="row"><button class="btn primary" id="draw-start">${icons.draw}${esc(t("ex.draw_start"))}</button></div>
        <div class="row" id="draw-ctl" hidden style="margin-top:10px">
          <button class="btn sm" id="draw-finish">${esc(t("ex.draw_finish"))}</button>
          <button class="btn sm ghost" id="draw-undo">${esc(t("ex.draw_undo"))}</button>
          <button class="btn sm ghost" id="draw-cancel">${esc(t("ex.draw_cancel"))}</button></div>`;
      $("#draw-start", body).addEventListener("click", () => {
        $("#draw-ctl", body).hidden = false;
        const hint = $("#draw-hint", main); hint.hidden = false;
        hint.innerHTML = `<div class="map-panel small strong">${esc(t("ex.draw_hint"))}</div>`;
        const d = fm.startDraw((geom) => {
          hint.hidden = true; $("#draw-ctl", body).hidden = true;
          compute({ name: getLang() === "fr" ? "Zone dessinée" : "Drawn zone", geometry: geom, kind: "drawn" });
        });
        $("#draw-finish", body).onclick = () => d.finish();
        $("#draw-undo", body).onclick = () => d.undo();
        $("#draw-cancel", body).onclick = () => { fm.stopDraw(); hint.hidden = true; $("#draw-ctl", body).hidden = true; };
      });
    } else if (state.tab === "upload") {
      body.innerHTML = `<label class="drop" id="drop">${icons.upload}<div style="margin-top:6px">${esc(t("ex.upload_drop"))}</div>
        <input type="file" accept=".geojson,.json,application/geo+json,application/json" hidden id="file"></label>
        <p class="help" style="margin-top:8px">Polygon / MultiPolygon · EPSG:4326 · FeatureCollection OK</p>`;
      const drop = $("#drop", body), file = $("#file", body);
      const read = async (f) => {
        try {
          const gj = JSON.parse(await f.text());
          const name = gj.name || gj.features?.[0]?.properties?.name || f.name.replace(/\.(geo)?json$/i, "");
          compute({ name, geometry: gj, kind: "upload" });
          toast(t("ex.upload_ok"));
        } catch (e) { toast("GeoJSON : " + e.message, true); }
      };
      file.addEventListener("change", () => file.files[0] && read(file.files[0]));
      ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && read(e.dataTransfer.files[0]));
    } else {
      body.innerHTML = `<div class="list" id="ref-list"><div class="card-pad"><div class="spinner"></div></div></div>`;
      const gj = await api.get("/api/reference-zones");
      $("#ref-list", body).innerHTML = gj.features.length ? gj.features.map((f, i) => `<button data-i="${i}"><span>${esc(f.properties.name)}</span>
        <span class="muted small">${esc(t("pro.cat." + f.properties.category) || f.properties.category)}</span></button>`).join("")
        : `<div class="card-pad muted small">${esc(t("ex.no_ref"))}</div>`;
      $$("#ref-list button", body).forEach((b) => b.addEventListener("click", () => {
        const f = gj.features[+b.dataset.i];
        compute({ name: f.properties.name, geometry: f.geometry, kind: "reference", category: f.properties.category });
      }));
    }
  }
  $$(".tabs button", main).forEach((b) => b.addEventListener("click", () => { state.tab = b.dataset.tab; renderTab(); }));
  renderTab();

  let cleanupZone = null;
  async function compute(zone) {
    state.zone = zone;
    const geom = zone.geometry.type === "FeatureCollection" || zone.geometry.type === "Feature" ? null : zone.geometry;
    if (geom) fm.setZone(geom);
    const res = $("#results", main);
    res.innerHTML = loadingBlock(t("ex.computing"));
    res.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const out = await api.post("/api/zone/calendar", { geometry: zone.geometry, name: zone.name, mode: state.mode, start_week: state.start, lang: getLang() });
      if (!geom && out) { /* uploaded collection: draw outline from first feature */
        const g = zone.geometry.type === "Feature" ? zone.geometry.geometry : zone.geometry.features?.[0]?.geometry;
        if (g) fm.setZone(g);
      }
      if (cleanupZone) cleanupZone();
      const actions = `<button class="btn sm" id="pdf-fr">${icons.doc}PDF FR</button><button class="btn sm" id="pdf-en">${icons.doc}PDF EN</button>
        <button class="btn sm primary" id="save-zone">${icons.pin}${esc(t("ex.save_zone"))}</button>`;
      cleanupZone = renderZone(res, out, {
        mode: state.mode, startWeek: state.start, extraActions: actions, geometry: zone.geometry,
        onMode: (m) => { state.mode = m; compute(zone); },
        onStart: (s) => { state.start = s; compute(zone); },
      });
      if (out.calendar.cells === 0 || out.calendar.years.every((y) => !y.total)) toast(t("ex.outside"), true);
      for (const l of ["fr", "en"]) {
        $(`#pdf-${l}`, res).addEventListener("click", async (e) => {
          const b = e.currentTarget; b.disabled = true;
          try { await api.download("/api/zone/bulletin", { geometry: zone.geometry, name: zone.name, lang: l, start_week: state.start }, `FireSync_${l}.pdf`); }
          catch (err) { toast(err.status === 401 ? t("common.login_required") : err.message, true); }
          b.disabled = false;
        });
      }
      $("#save-zone", res).addEventListener("click", () => saveZone(zone));
    } catch (e) {
      res.innerHTML = errorBlock(e);
    }
  }

  async function saveZone(zone) {
    if (!FS.user) { location.hash = "#/login?next=explorer"; return; }
    const cats = ["departement", "foret_classee", "parcours", "aire_protegee", "autre"];
    const v = await modal(t("ex.save_zone"), `
      <div class="field"><label for="zn">${esc(t("ex.zone_name"))}</label><input class="input" id="zn" value="${esc(zone.name)}"></div>
      <div class="field"><label for="zc">${esc(t("pro.category"))}</label><select class="input" id="zc">
        ${cats.map((c) => `<option value="${c}" ${(zone.category || (zone.kind === "admin" ? "departement" : "")) === c ? "selected" : ""}>${esc(t("pro.cat." + c))}</option>`).join("")}</select></div>
      <div class="field"><label for="za">${esc(t("pro.alert_pct"))}</label><input class="input" id="za" type="number" min="50" max="100" value="90"></div>`, {
      actions: [{ label: t("common.cancel"), value: null }, { label: t("common.save"), primary: true,
        value: (b) => ({ name: b.querySelector("#zn").value, category: b.querySelector("#zc").value, alert_pct: +b.querySelector("#za").value }) }],
    });
    if (!v) return;
    try {
      await api.post("/api/pro/zones", { ...v, geometry: zone.geometry, kind: zone.kind === "reference" ? "drawn" : zone.kind });
      toast(t("ex.saved"));
    } catch (e) { toast(e.message, true); }
  }

  if (!state.zone) {
    $("#results", main).innerHTML = emptyBlock(icons.map, t("ex.empty_t"), t("ex.empty_d"));
  } else compute(state.zone);

  return () => { if (cleanupZone) cleanupZone(); fm.remove(); };
}
