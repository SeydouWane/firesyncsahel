import { api } from "../api.js";
import { t } from "../i18n.js";
import { $, esc } from "../ui.js";
import { logoSVG } from "../logo.js";
import { setUser, FS } from "../main.js";

export async function render(main, { query }) {
  if (FS.user) { location.hash = FS.user.role === "admin" ? "#/admin" : "#/pro"; return; }
  main.innerHTML = `<div class="auth-wrap"><form class="card auth-card" id="f" autocomplete="on">
    <div style="display:flex;justify-content:center">${logoSVG({ size: 72 })}</div>
    <h1 style="text-align:center">${esc(t("auth.title"))}</h1><p class="ink2 small" style="text-align:center;margin-bottom:18px">${esc(t("auth.sub"))}</p>
    <div class="field"><label for="em">${esc(t("common.email"))}</label><input class="input" id="em" type="email" required autocomplete="username"></div>
    <div class="field"><label for="pw">${esc(t("auth.password"))}</label><input class="input" id="pw" type="password" required autocomplete="current-password"></div>
    <p class="small" id="err" style="color:var(--crit-ink)" hidden></p>
    <button class="btn primary lg" style="width:100%" type="submit">${esc(t("auth.submit"))}</button>
    <p class="small ink2" style="text-align:center;margin:14px 0 0">${esc(t("auth.no_account"))} <a href="#/about">${esc(t("auth.request"))}</a></p>
  </form></div>`;
  $("#em", main).focus();
  $("#f", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#err", main); err.hidden = true;
    try {
      const r = await api.post("/api/auth/login", { email: $("#em").value, password: $("#pw").value });
      setUser(r.user);
      const next = query.get("next");
      location.hash = next ? `#/${next}` : (r.user.role === "admin" ? "#/admin" : "#/pro");
    } catch (ex) {
      err.textContent = ex.status === 429 ? ex.message : t("auth.bad"); err.hidden = false;
    }
  });
}
