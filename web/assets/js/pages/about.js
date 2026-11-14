import { api } from "../api.js";
import { t } from "../i18n.js";
import { $, esc, icons, toast } from "../ui.js";
import { logoSVG } from "../logo.js";
import { footer } from "./data.js";

export async function render(main) {
  const persp = t("about.persp");
  main.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(t("space.public"))}</div><h1>${esc(t("about.title"))}</h1>
    <p class="sub">${esc(t("about.sub"))}</p></div></div>
    <div class="grid g2">
      <div class="stack">
        <div class="card card-pad" style="display:flex;gap:18px;align-items:center">${logoSVG({ size: 92 })}
          <div><h3 style="font-size:18px">FireSync Sahel</h3><p class="ink2" style="margin:6px 0 0">${esc(t("home.lead"))}</p></div></div>
        <div class="card card-pad"><h3 style="font-size:15px;margin-bottom:10px">${esc(t("about.persp_t"))}</h3>
          <ul style="margin:0;padding-left:18px;display:grid;gap:6px">${persp.map((p) => `<li class="ink2">${esc(p)}</li>`).join("")}</ul></div>
      </div>
      <form class="card card-pad" id="req">
        <h3 style="font-size:17px">${esc(t("about.req_t"))}</h3><p class="ink2 small" style="margin:6px 0 16px">${esc(t("about.req_d"))}</p>
        <div class="grid g2" style="gap:0 12px">
          <div class="field"><label for="rn">${esc(t("common.name"))}</label><input class="input" id="rn" required minlength="2" autocomplete="name"></div>
          <div class="field"><label for="re">${esc(t("common.email"))}</label><input class="input" id="re" type="email" required autocomplete="email"></div>
        </div>
        <div class="field"><label for="ro">${esc(t("common.org"))}</label><input class="input" id="ro" autocomplete="organization"></div>
        <div class="field"><label for="rp">${esc(t("about.profile"))}</label><select class="input" id="rp">
          ${["p_forest", "p_committee", "p_pastoral", "p_research", "p_ew", "p_other"].map((k) => `<option>${esc(t("about." + k))}</option>`).join("")}</select></div>
        <div class="field"><label for="rm">${esc(t("about.message"))}</label><textarea class="input" id="rm" maxlength="2000"></textarea></div>
        <button class="btn primary" type="submit">${icons.check}${esc(t("about.send"))}</button>
      </form>
    </div>${footer()}`;
  $("#req", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api.post("/api/access-request", { name: $("#rn").value, email: $("#re").value, org: $("#ro").value, profile: $("#rp").value, message: $("#rm").value });
      e.target.innerHTML = `<div class="empty"><div class="ic">${icons.check}</div><h3>${esc(t("about.sent"))}</h3></div>`;
    } catch (err) { toast(err.message, true); }
  });
}
