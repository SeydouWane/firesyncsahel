// Small DOM / formatting helpers shared by pages.
import { t, getLang } from "./i18n.js";

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export function h(html) { const d = document.createElement("template"); d.innerHTML = html.trim(); return d.content.firstElementChild; }
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// "Papa Seydou WANE" -> "PW" (first + last word); a single word or an e-mail -> its first 2 letters
export function initials(u) {
  const w = String(u?.name || "").trim().split(/\s+/).filter(Boolean);
  if (w.length >= 2) return (w[0][0] + w[w.length - 1][0]).toUpperCase();
  return String(u?.name || u?.email || "?").slice(0, 2).toUpperCase();
}

export function toast(msg, err = false) {
  const el = h(`<div class="toast${err ? " err" : ""}" role="status">${esc(msg)}</div>`);
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), err ? 6000 : 3500);
}

export function modal(title, bodyHtml, { actions = [] } = {}) {
  return new Promise((resolve) => {
    const back = h(`<div class="modal-back" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="card modal"><h3>${esc(title)}</h3><div class="mbody">${bodyHtml}</div>
      <div class="row" style="justify-content:flex-end;margin-top:16px"></div></div></div>`);
    const row = back.querySelector(".row");
    const close = (v) => { back.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    (actions.length ? actions : [{ label: t("common.close"), value: null }]).forEach((a) => {
      const b = h(`<button class="btn ${a.primary ? "primary" : ""} ${a.danger ? "danger" : ""}">${esc(a.label)}</button>`);
      b.onclick = () => close(typeof a.value === "function" ? a.value(back) : a.value);
      row.appendChild(b);
    });
    back.addEventListener("click", (e) => { if (e.target === back) close(null); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(back);
    (back.querySelector("input,select,textarea,button.primary") || back.querySelector("button"))?.focus();
  });
}

export async function confirmBox(text) {
  return modal(t("common.confirm"), `<p>${esc(text)}</p>`, {
    actions: [{ label: t("common.cancel"), value: false }, { label: t("common.confirm"), value: true, primary: true }],
  });
}

// "12 %" / "12%", "Label : x" / "Label: x" (French typography uses a non-breaking space)
export const PCT = () => (getLang() === "fr" ? " %" : "%");
export const COLON = () => (getLang() === "fr" ? " :" : ":");

const nf = () => new Intl.NumberFormat(getLang() === "fr" ? "fr-FR" : "en-GB", { maximumFractionDigits: 0 });
export function fmt(v, d = 0) {
  if (v == null || Number.isNaN(v)) return "–";
  return new Intl.NumberFormat(getLang() === "fr" ? "fr-FR" : "en-GB", { maximumFractionDigits: d, minimumFractionDigits: d }).format(v);
}
export const fmtInt = (v) => (v == null ? "–" : nf().format(v));
export function fmtSigned(v, d = 1, unit = "") {
  if (v == null || Number.isNaN(v)) return "–";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v), d)}${unit}`;
}
export function fmtDate(ts) {
  if (!ts) return "–";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleString(getLang() === "fr" ? "fr-FR" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}
export function fmtDay(iso) {
  if (!iso) return "–";
  return new Date(iso + "T00:00:00").toLocaleDateString(getLang() === "fr" ? "fr-FR" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
}

export const STATUS = {
  above_p90: { cls: "crit", icon: "▲▲", color: "var(--crit)" },
  p75_p90: { cls: "warn", icon: "▲", color: "var(--warn)" },
  normal: { cls: "ok", icon: "●", color: "var(--ok)" },
  p10_p25: { cls: "low", icon: "▼", color: "var(--muted)" },
  below_p10: { cls: "low", icon: "▼▼", color: "var(--muted)" },
  nodata: { cls: "low", icon: "–", color: "var(--muted)" },
  offseason: { cls: "low", icon: "·", color: "var(--muted)" },
  few: { cls: "low", icon: "∅", color: "var(--muted)" },
};
export function statusChip(s) {
  const st = STATUS[s] || STATUS.nodata;
  return `<span class="chip ${st.cls}"><span aria-hidden="true">${st.icon}</span>${esc(t("status." + (s || "nodata")))}</span>`;
}
export const RISK = {
  high: { cls: "crit", icon: "▲▲", fill: "#d03b3b" },
  moderate: { cls: "warn", icon: "▲", fill: "#fab219" },
  low: { cls: "ok", icon: "●", fill: "#0ca30c" },
  offseason: { cls: "low", icon: "·", fill: "#b8b2a8" },
};
export function riskChip(r) {
  const x = RISK[r] || RISK.offseason;
  return `<span class="chip ${x.cls}"><span aria-hidden="true">${x.icon}</span>${esc(t("risk." + (r || "offseason")))}</span>`;
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (e2) {} ta.remove(); return ok;
  }
}
export function srcColor(s) {
  if (s === "VIIRS_SNPP") return "var(--src-viirs)";
  if (s === "N20" || s === "N21") return "var(--src-n20)";
  return "var(--src-modis)";
}
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function loadingBlock(text) {
  return `<div class="card card-pad"><div class="row"><div class="spinner"></div><span class="ink2">${esc(text || t("common.loading"))}</span></div>
    <div class="progress" style="margin-top:12px"></div></div>`;
}
export function errorBlock(e) {
  return `<div class="card card-pad"><b>${esc(t("common.error"))}</b><p class="ink2 small" style="margin-top:6px">${esc(e?.message || e)}</p></div>`;
}
export function emptyBlock(icon, title, text, actionHtml = "") {
  return `<div class="card empty"><div class="ic">${icon}</div><h3>${esc(title)}</h3><p class="ink2" style="max-width:460px;margin:8px auto 14px">${esc(text)}</p>${actionHtml}</div>`;
}

// inline SVG icons (stroke, 18px)
const I = (p, s = 18) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
export const icons = {
  home: I('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>'),
  map: I('<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>'),
  flame: I('<path d="M12 3c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 3-1-3 0-5 0-7z"/>'),
  method: I('<path d="M4 19h16"/><path d="M6 15l4-5 3 3 5-7"/>'),
  data: I('<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>'),
  info: I('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'),
  dash: I('<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>'),
  pin: I('<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>'),
  chart: I('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  doc: I('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>'),
  user: I('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  users: I('<circle cx="9" cy="8" r="3.5"/><path d="M2 20a7 7 0 0 1 14 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M22 20a7 7 0 0 0-4-6.3"/>'),
  layers: I('<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>'),
  gear: I('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  log: I('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
  cpu: I('<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
  sun: I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: I('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
  draw: I('<path d="M3 17l6-12 6 8 6-4"/><circle cx="3" cy="17" r="1.5"/><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="13" r="1.5"/><circle cx="21" cy="9" r="1.5"/>'),
  upload: I('<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>'),
  download: I('<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 18v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>'),
  bell: I('<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>'),
  shield: I('<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>'),
  tree: I('<path d="M12 22v-6"/><path d="M12 2 6 10h3l-4 6h14l-4-6h3z"/>'),
  cow: I('<path d="M5 9c0-3 2-5 7-5s7 2 7 5v4a7 7 0 0 1-14 0z"/><path d="M5 7 2 5M19 7l3-2"/><circle cx="9.5" cy="10" r=".8"/><circle cx="14.5" cy="10" r=".8"/>'),
  lab: I('<path d="M9 3h6M10 3v6L4 19a1.5 1.5 0 0 0 1.3 2h13.4A1.5 1.5 0 0 0 20 19l-6-10V3"/>'),
  alert: I('<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>'),
  sat: I('<path d="m13 7 4 4M8 12l4 4"/><rect x="9.5" y="7.5" width="5" height="9" rx="1" transform="rotate(45 12 12)"/><path d="M4 20c0-3 1-5 3-6M20 4c-3 0-5 1-6 3"/>'),
  check: I('<path d="M5 12l5 5 9-10"/>'),
  spark: I('<path d="M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>'),
  sms: I('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8 11h8M8 14h5"/>'),
  copy: I('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>'),
  plus: I('<path d="M12 5v14M5 12h14"/>'),
  bulb: I('<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>'),
  arrow: I('<path d="M5 12h14M13 6l6 6-6 6"/>'),
  calendar: I('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
  gauge: I('<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>'),
  question: I('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 0 1 4.9.7c0 1.7-2.4 2.1-2.4 3.8M12 17h.01"/>'),
  logout: I('<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>'),
};

// tooltip
export function showTip(e, html) {
  const tip = $("#tip");
  tip.innerHTML = html; tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, hgt = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth - 8) x = e.clientX - w - pad;
  if (y + hgt > innerHeight - 8) y = e.clientY - hgt - pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
export const hideTip = () => { $("#tip").hidden = true; };
