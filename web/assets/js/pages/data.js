import { t, getLang } from "../i18n.js";
import { esc, icons, fmtInt, fmtDay } from "../ui.js";
import { FS } from "../main.js";

const SOURCES = [
  { mark: "FIRMS", name: "NASA FIRMS", d: { fr: "Feux actifs MODIS C6.1 & VIIRS 375 m (archives + quasi temps réel)", en: "MODIS C6.1 & VIIRS 375 m active fires (archive + NRT)" }, url: "https://firms.modaps.eosdis.nasa.gov/" },
  { mark: "MODIS", name: "Terra · Aqua", d: { fr: "Détections 1 km depuis 2000 / 2002", en: "1 km detections since 2000 / 2002" }, url: "https://modis.gsfc.nasa.gov/" },
  { mark: "VIIRS", name: "S-NPP · NOAA-20 · NOAA-21", d: { fr: "Détections 375 m depuis 2012", en: "375 m detections since 2012" }, url: "https://www.earthdata.nasa.gov/data/instruments/viirs" },
  { mark: "LC", name: "MCD12Q1 v061", d: { fr: "Occupation du sol MODIS (stratification)", en: "MODIS land cover (stratification)" }, url: "https://lpdaac.usgs.gov/products/mcd12q1v061/" },
  { mark: "BA", name: "MCD64A1 v061", d: { fr: "Surfaces brûlées MODIS (validation indépendante)", en: "MODIS burned area (independent validation)" }, url: "https://lpdaac.usgs.gov/products/mcd64a1v061/" },
  { mark: "ADM", name: "geoBoundaries", d: { fr: "Limites administratives (CC BY 3.0 IGO)", en: "Administrative boundaries (CC BY 3.0 IGO)" }, url: "https://www.geoboundaries.org/" },
];

export function dataStrip() {
  const l = getLang();
  return `<div class="data-strip">${SOURCES.map((s) => `<a class="data-pill" href="${s.url}" target="_blank" rel="noopener">
    <span class="mark">${esc(s.mark)}</span><span><b>${esc(s.name)}</b><span>${esc(s.d[l])}</span></span></a>`).join("")}</div>`;
}

// Organisations whose data FireSync uses (text tiles: their logos are not reproduced)
const PROVIDERS = [
  { mark: "FIRMS", name: "NASA · LANCE FIRMS", by: "ESDIS · Goddard Space Flight Center",
    d: { fr: "Feux actifs MODIS & VIIRS, archives et temps quasi réel", en: "MODIS & VIIRS active fires, archive and near real time" }, url: "https://firms.modaps.eosdis.nasa.gov/" },
  { mark: "LP", name: "NASA LP DAAC · Earthdata", by: "USGS EROS",
    d: { fr: "MCD12Q1 (occupation du sol), MCD64A1 (surfaces brûlées), MOD13A1 (NDVI)", en: "MCD12Q1 (land cover), MCD64A1 (burned area), MOD13A1 (NDVI)" }, url: "https://lpdaac.usgs.gov/" },
  { mark: "JPSS", name: "NOAA · NASA JPSS", by: "Joint Polar Satellite System",
    d: { fr: "Satellites S-NPP, NOAA-20 et NOAA-21 (instrument VIIRS)", en: "S-NPP, NOAA-20 and NOAA-21 satellites (VIIRS instrument)" }, url: "https://www.nesdis.noaa.gov/our-satellites/currently-flying/joint-polar-satellite-system" },
  { mark: "PC", name: "Microsoft Planetary Computer", by: "",
    d: { fr: "Accès cloud aux produits MODIS (MCD64A1, MOD13A1)", en: "Cloud access to MODIS products (MCD64A1, MOD13A1)" }, url: "https://planetarycomputer.microsoft.com/" },
  { mark: "ADM", name: "geoBoundaries", by: "William & Mary geoLab",
    d: { fr: "Limites administratives ADM1 / ADM2 (CC BY 3.0 IGO)", en: "ADM1 / ADM2 administrative boundaries (CC BY 3.0 IGO)" }, url: "https://www.geoboundaries.org/" },
  { mark: "OSM", name: "OpenStreetMap · CARTO", by: "",
    d: { fr: "Fonds de carte (© contributeurs OpenStreetMap, © CARTO)", en: "Basemaps (© OpenStreetMap contributors, © CARTO)" }, url: "https://www.openstreetmap.org/copyright" },
];
const ROLE = { challenge: { fr: "Défi", en: "Challenge" }, partner: { fr: "Partenaire", en: "Partner" }, data: { fr: "Données", en: "Data" } };

function logoTile(x, size = "") {
  const img = `<img src="${esc(x.logo)}" alt="${esc(x.name)}" loading="lazy">`;
  const cls = `logo-tile${x.dark ? " dark" : ""}${size ? " " + size : ""}`;
  return x.url ? `<a class="${cls}" href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(x.name)}">${img}</a>`
    : `<span class="${cls}" title="${esc(x.name)}">${img}</span>`;
}

// compact row of logos (hero, footer)
export function partnerLogos(size = "sm") {
  const p = (FS.meta?.partners || []).filter((x) => x.logo);
  return p.length ? `<div class="partner-row">${p.map((x) => logoTile(x, size)).join("")}</div>` : "";
}

export function partnersBlock() {
  const l = getLang();
  const p = FS.meta?.partners || [];
  return `<div class="card card-pad partners" style="margin-top:14px">
    ${p.length ? `<div class="small strong muted" style="margin-bottom:12px">${l === "fr" ? "Cadre du projet & partenaires" : "Project framework & partners"}</div>
    <div class="partner-cards">${p.map((x) => `<div class="partner-card">${x.logo ? logoTile(x) : `<span class="logo-tile text">${esc(x.name)}</span>`}
      <div><span class="chip">${esc((ROLE[x.role] || ROLE.partner)[l])}</span><div class="small ink2" style="margin-top:4px">${esc(x.name)}</div></div></div>`).join("")}</div>
    <hr class="divider">` : ""}
    <div class="small strong muted" style="margin-bottom:10px">${l === "fr" ? "Organisations fournisseurs de données" : "Data provider organisations"}</div>
    <div class="provider-grid">${PROVIDERS.map((s) => `<a class="data-pill" href="${s.url}" target="_blank" rel="noopener">
      <span class="mark">${esc(s.mark)}</span><span><b>${esc(s.name)}</b><span>${esc(s.d[l])}${s.by ? ` · ${esc(s.by)}` : ""}</span></span></a>`).join("")}</div>
    <p class="small muted" style="margin:12px 0 0">${l === "fr"
      ? "Projet développé dans le cadre du NASA Space Apps Challenge (Dakar). FireSync Sahel n'est pas un produit officiel de la NASA ni des organisations citées ; leurs données sont utilisées selon leurs licences ouvertes."
      : "Project built for the NASA Space Apps Challenge (Dakar). FireSync Sahel is not an official product of NASA or of the organisations listed; their data are used under their open licences."}</p></div>`;
}

export function footer() {
  const m = FS.meta;
  const ack = m?.ack?.[getLang()] || "";
  return `<footer class="footer"><div class="row" style="justify-content:space-between;align-items:center;gap:16px">
    <div class="ack">${esc(ack)}</div>${partnerLogos("xs")}</div>
    <div style="margin-top:10px">FireSync Sahel ${m ? "v" + esc(m.version) : ""} · ${m ? esc(t("common.data_to")) + " " + esc(fmtDay(m.last_date)) : ""}</div></footer>`;
}

export async function render(main) {
  const m = FS.meta;
  const l = getLang();
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("space.public"))}</div><h1>${esc(t("data.title"))}</h1>
    <p class="sub">${esc(t("data.sub"))}</p></div></div>
    ${dataStrip()}
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h3>${esc(t("adm.coverage"))}</h3></div><div class="card-body"><div class="table-wrap"><table class="table">
        <thead><tr><th>Capteur / Sensor</th><th>${esc(t("adm.first"))}</th><th>${esc(t("adm.last"))}</th><th class="num">${esc(t("adm.count"))}</th></tr></thead>
        <tbody>${(m?.sensors || []).map((s) => `<tr><td>${esc(s.sensor.replace("_", " "))}</td><td>${esc(s.first)}</td><td>${esc(s.last)}</td><td class="num">${fmtInt(s.n)}</td></tr>`).join("")}</tbody></table></div>
        <p class="small muted" style="margin-top:10px">${l === "fr" ? "Filtres : feux de végétation présumés (type 0), confiance faible exclue. Zone couverte :" : "Filters: presumed vegetation fires (type 0), low confidence removed. Covered area:"}
          ${esc((m?.countries || []).join(", ").replace(/_/g, " "))}.</p></div></div>
      <div class="card"><div class="card-head"><h3>${esc(t("method.lc_used"))}</h3></div><div class="card-body">
        <p><b>${esc(m?.land_cover?.product || "–")}</b></p>
        <p class="ink2 small">${l === "fr" ? "Six groupes : forêt, savane, arbustes, prairie, cultures, autres." : "Six groups: forest, savanna, shrubland, grassland, cropland, other."}</p>
        <hr class="divider"><h3 style="font-size:15px;margin-bottom:8px">${l === "fr" ? "Continuité après Suomi NPP" : "Continuity after Suomi NPP"}</h3>
        <p class="ink2 small">${esc(t("home.snpp"))}</p>
        <p class="small">${m?.nrt_configured ? `<span class="chip ok">${icons.check} NRT</span>` : `<span class="chip warn">NRT</span> <span class="muted">${esc(t("adm.nrt_missing"))}</span>`}</p>
      </div></div>
    </div>
    <div class="card card-pad" style="margin-top:16px"><h3 style="font-size:15px;margin-bottom:8px">${esc(t("data.ack_t"))}</h3>
      <p class="ink2">${esc(m?.ack?.[l] || "")}</p>
      </div>
    ${partnersBlock()}
    ${footer()}`;
}
