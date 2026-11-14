// Boot, router and shell (top bar + per-space sidebar).
import { api } from "./api.js";
import { t, getLang, setLang } from "./i18n.js";
import { $, $$, esc, icons, toast, fmtDay } from "./ui.js";
import { logoSVG } from "./logo.js";

export const FS = { meta: null, user: null, metaError: null };

const ROUTES = {
  "": { space: "public", page: "home", load: () => import("./pages/home.js") },
  explorer: { space: "public", page: "explorer", load: () => import("./pages/explorer.js") },
  season: { space: "public", page: "season", load: () => import("./pages/season.js") },
  forecast: { space: "public", page: "forecast", load: () => import("./pages/forecast.js") },
  method: { space: "public", page: "method", load: () => import("./pages/method.js") },
  data: { space: "public", page: "data", load: () => import("./pages/data.js") },
  about: { space: "public", page: "about", load: () => import("./pages/about.js") },
  login: { space: "public", page: "login", load: () => import("./pages/login.js") },
  pro: { space: "pro", page: "dashboard", auth: "pro", load: () => import("./pages/pro.js") },
  "pro/zones": { space: "pro", page: "zones", auth: "pro", load: () => import("./pages/pro.js") },
  "pro/analysis": { space: "pro", page: "analysis", auth: "pro", load: () => import("./pages/pro.js") },
  "pro/bulletins": { space: "pro", page: "bulletins", auth: "pro", load: () => import("./pages/pro.js") },
  "pro/account": { space: "pro", page: "account", auth: "pro", load: () => import("./pages/pro.js") },
  admin: { space: "admin", page: "overview", auth: "admin", load: () => import("./pages/admin.js") },
  "admin/pipeline": { space: "admin", page: "pipeline", auth: "admin", load: () => import("./pages/admin.js") },
  "admin/model": { space: "admin", page: "model", auth: "admin", load: () => import("./pages/method.js") },
  "admin/users": { space: "admin", page: "users", auth: "admin", load: () => import("./pages/admin.js") },
  "admin/refzones": { space: "admin", page: "refzones", auth: "admin", load: () => import("./pages/admin.js") },
  "admin/settings": { space: "admin", page: "settings", auth: "admin", load: () => import("./pages/admin.js") },
  "admin/audit": { space: "admin", page: "audit", auth: "admin", load: () => import("./pages/admin.js") },
};

const SIDEBAR = {
  public: [
    { title: "nav.s_discover" },
    { href: "#/", key: "home", icon: "home", label: "nav.home" },
    { href: "#/explorer", key: "explorer", icon: "map", label: "nav.explorer" },
    { href: "#/season", key: "season", icon: "flame", label: "nav.season" },
    { href: "#/forecast", key: "forecast", icon: "spark", label: "nav.forecast" },
    { href: "#/method", key: "method", icon: "method", label: "nav.method" },
    { href: "#/data", key: "data", icon: "data", label: "nav.data" },
    { href: "#/about", key: "about", icon: "info", label: "nav.about" },
  ],
  pro: [
    { title: "nav.s_pro" },
    { href: "#/pro", key: "dashboard", icon: "dash", label: "nav.dashboard" },
    { href: "#/pro/zones", key: "zones", icon: "pin", label: "nav.zones" },
    { href: "#/pro/analysis", key: "analysis", icon: "chart", label: "nav.analysis" },
    { href: "#/pro/bulletins", key: "bulletins", icon: "doc", label: "nav.bulletins" },
    { href: "#/explorer", key: "_explorer", icon: "map", label: "nav.explorer" },
    { href: "#/pro/account", key: "account", icon: "user", label: "nav.account" },
  ],
  admin: [
    { title: "nav.s_admin" },
    { href: "#/admin", key: "overview", icon: "dash", label: "nav.overview" },
    { href: "#/admin/pipeline", key: "pipeline", icon: "cpu", label: "nav.pipeline" },
    { href: "#/admin/model", key: "model", icon: "method", label: "nav.model" },
    { href: "#/admin/users", key: "users", icon: "users", label: "nav.users", badge: "requests" },
    { href: "#/admin/refzones", key: "refzones", icon: "layers", label: "nav.refzones" },
    { href: "#/admin/settings", key: "settings", icon: "gear", label: "nav.settings" },
    { href: "#/admin/audit", key: "audit", icon: "log", label: "nav.audit" },
  ],
};

let current = { route: null, cleanup: null };
export let pendingRequests = 0;

function parseHash() {
  const raw = (location.hash || "#/").replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  let key = parts.join("/"), param = null;
  if (!ROUTES[key] && parts.length > 1) { key = parts.slice(0, -1).join("/"); param = decodeURIComponent(parts[parts.length - 1]); }
  return { key: ROUTES[key] ? key : "", param, query: new URLSearchParams(qs || "") };
}

const TOP_NAV = [
  { href: "#/", key: "home", label: "nav.home" },
  { href: "#/explorer", key: "explorer", label: "nav.explorer_short" },
  { href: "#/season", key: "season", label: "nav.season" },
  { href: "#/forecast", key: "forecast", label: "nav.forecast", ai: true },
  { href: "#/method", key: "method", label: "nav.method_short" },
  { href: "#/data", key: "data", label: "nav.data_short" },
  { href: "#/about", key: "about", label: "nav.about_short" },
];

function renderTop(space, page) {
  $("#brand").innerHTML = `${logoSVG({ size: 36 })}<div><div class="wordmark">FireSync <span>Sahel</span></div><small>${esc(t("tagline"))}</small></div>`;
  const u = FS.user;
  document.body.classList.toggle("space-public", space === "public");
  $("#top-nav").innerHTML = space === "public" ? TOP_NAV.map((n) => `<a href="${n.href}" class="${n.key === page ? "active" : ""}"
      ${n.key === page ? 'aria-current="page"' : ""}>${esc(t(n.label))}${n.ai ? ' <span class="ai-tag">IA</span>' : ""}</a>`).join("") : "";
  const sw = [];
  if (u) {
    sw.push(`<a href="#/" class="${space === "public" ? "active" : ""}">${esc(t("space.public"))}</a>`);
    sw.push(`<a href="#/pro" class="${space === "pro" ? "active" : ""}">${esc(t("space.pro"))}</a>`);
    if (u.role === "admin") sw.push(`<a href="#/admin" class="${space === "admin" ? "active" : ""}">${esc(t("space.admin"))}</a>`);
  }
  $("#space-switch").innerHTML = sw.join("");
  $("#space-switch").hidden = !u;
  $$(".lang-toggle button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === getLang())));
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#theme-btn").innerHTML = dark ? icons.sun : icons.moon;
  $("#theme-btn").setAttribute("aria-label", dark ? "Light theme" : "Dark theme");
  $("#user-slot").innerHTML = u
    ? `<button class="user-chip" id="user-btn" title="${esc(u.email)}"><span class="avatar">${esc((u.name || u.email).slice(0, 2).toUpperCase())}</span>
         <span class="name small strong">${esc(u.name || u.email)}</span></button>`
    : `<a class="btn sm primary" href="#/login">${esc(t("nav.login"))}</a>`;
  $("#user-btn")?.addEventListener("click", () => { location.hash = u.role === "admin" && space !== "pro" ? "#/admin" : "#/pro/account"; });
}

function renderSide(space, page) {
  const items = SIDEBAR[space];
  const html = items.map((it) => {
    if (it.title) return `<div class="side-title">${esc(t(it.title))}</div>`;
    const badge = it.badge === "requests" && pendingRequests ? `<span class="count">${pendingRequests}</span>` : "";
    return `<a class="side-link ${it.key === page ? "active" : ""}" href="${it.href}">${icons[it.icon]}<span>${esc(t(it.label))}</span>${badge}</a>`;
  });
  if (space === "public" && FS.user) {
    html.push(`<div class="side-title">${esc(t("nav.s_pro"))}</div>
      <a class="side-link" href="#/pro">${icons.dash}<span>${esc(t("nav.dashboard"))}</span></a>`);
    if (FS.user.role === "admin") html.push(`<a class="side-link" href="#/admin">${icons.shield}<span>${esc(t("space.admin"))}</span></a>`);
  }
  if (space !== "public") html.push(`<div class="side-title"></div><a class="side-link" href="#/">${icons.home}<span>${esc(t("nav.back_public"))}</span></a>`);
  if (FS.user) html.push(`<a class="side-link" href="#" id="logout-link">${icons.logout}<span>${esc(t("nav.logout"))}</span></a>`);
  const m = FS.meta;
  html.push(`<div class="side-foot"><div class="data-badge">${icons.sat}<span>NASA FIRMS · MODIS · VIIRS</span></div>
    ${m ? `${esc(t("common.data_to"))} ${esc(fmtDay(m.last_date))}` : ""}</div>`);
  $("#sidebar").innerHTML = html.join("");
  $("#logout-link")?.addEventListener("click", async (e) => {
    e.preventDefault();
    await api.post("/api/auth/logout");
    FS.user = null; toast(t("nav.logout")); location.hash = "#/"; route();
  });
}

export async function route() {
  const { key, param, query } = parseHash();
  const r = ROUTES[key];
  if (r.auth && !FS.user) { location.hash = `#/login?next=${encodeURIComponent(key)}`; return; }
  if (r.auth === "admin" && FS.user?.role !== "admin") { location.hash = "#/pro"; return; }
  if (current.cleanup) { try { current.cleanup(); } catch (e) {} current.cleanup = null; }
  document.body.classList.remove("nav-open");
  $("#menu-btn").setAttribute("aria-expanded", "false");
  renderTop(r.space, r.page);
  renderSide(r.space, r.page);
  const main = $("#main");
  main.innerHTML = "";
  current.route = key;
  try {
    const mod = await r.load();
    current.cleanup = (await mod.render(main, { page: r.page, param, query, space: r.space })) || null;
  } catch (e) {
    console.error(e);
    main.innerHTML = `<div class="card card-pad"><b>${esc(t("common.error"))}</b><p class="small ink2">${esc(e.message)}</p></div>`;
  }
  main.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

export function rerender() { route(); }
export function setUser(u) { FS.user = u; }
export function refreshBadges(n) { pendingRequests = n; }

async function boot() {
  try {
    FS.meta = await api.get("/api/meta");
    FS.user = FS.meta.user;
  } catch (e) {
    FS.metaError = e;
    try { FS.user = (await api.get("/api/auth/me")).user; } catch (e2) {}
  }
  $$(".lang-toggle button").forEach((b) => b.addEventListener("click", () => { setLang(b.dataset.lang); route(); }));
  $("#theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("fs-theme", root.dataset.theme); } catch (e) {}
    route();
  });
  $("#menu-btn").addEventListener("click", () => {
    const open = document.body.classList.toggle("nav-open");
    $("#menu-btn").setAttribute("aria-expanded", String(open));
  });
  $("#overlay").addEventListener("click", () => document.body.classList.remove("nav-open"));
  window.addEventListener("hashchange", route);
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => window.dispatchEvent(new Event("fs-resize")), 250); });
  route();
}
boot();
