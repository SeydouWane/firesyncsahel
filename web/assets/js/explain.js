// Plain-language explanations of the numbers (FR / EN), written for non-specialist users:
// each function turns API values into short sentences ("in plain words").
import { getLang } from "./i18n.js";
import { esc, fmt, fmtInt, icons } from "./ui.js";

const FR = () => getLang() === "fr";
const L = (fr, en) => (FR() ? fr : en);
const b = (x) => `<b>${x}</b>`;
// French typography: no line break before ? : ! ; » (non-breaking space)
export const typo = (s) => (FR() && s ? String(s).replace(/ ([?:!;»])/g, " $1").replace(/« /g, "« ") : s);

// friendly rounding for sentences: 6100.7 -> 6 100, 453 -> 450, 37 -> 37
export function about(x) {
  if (x == null || Number.isNaN(x)) return "–";
  const a = Math.abs(x);
  const step = a >= 10000 ? 100 : a >= 1000 ? 50 : a >= 200 ? 10 : 1;
  return fmtInt(Math.round(x / step) * step);
}

// ---------------------------------------------------------------- building blocks
export function plainBox(paras, { title, cls = "" } = {}) {
  const body = paras.filter(Boolean).map((p) => (p.startsWith("<ul") ? p : `<p>${p}</p>`)).join("");
  return `<div class="plain ${cls}"><div class="plain-ic" aria-hidden="true">${icons.bulb}</div>
    <div class="plain-body"><div class="plain-t">${esc(title || L("En clair", "In plain words"))}</div>${typo(body)}</div></div>`;
}

export function howTo(text) {
  return `<p class="howto"><span class="howto-ic" aria-hidden="true">${icons.info}</span>
    <span><b>${typo(esc(L("Comment lire :", "How to read:")))}</b> ${typo(esc(text))}</span></p>`;
}

// ---------------------------------------------------------------- vocabulary
// level of a total against history ("this is ... for this date")
const LEVEL = {
  fr: { above_p90: "bien au-dessus de la normale", p75_p90: "au-dessus de la normale", normal: "dans la normale",
        p10_p25: "en dessous de la normale", below_p10: "bien en dessous de la normale", few: "trop faible pour être comparé au passé",
        offseason: "hors saison des feux", nodata: "sans donnée" },
  en: { above_p90: "well above normal", p75_p90: "above normal", normal: "within normal",
        p10_p25: "below normal", below_p10: "well below normal", few: "too low to compare with the past",
        offseason: "outside the fire season", nodata: "without data" },
};
// how active a week was
const ACTIVITY = {
  fr: { above_p90: "bien plus active que d'habitude", p75_p90: "plus active que d'habitude", normal: "dans la normale",
        p10_p25: "plus calme que d'habitude", below_p10: "bien plus calme que d'habitude", few: "très calme",
        offseason: "hors saison", nodata: "sans donnée" },
  en: { above_p90: "much busier than usual", p75_p90: "busier than usual", normal: "within normal",
        p10_p25: "quieter than usual", below_p10: "much quieter than usual", few: "very quiet",
        offseason: "off-season", nodata: "without data" },
};
export const levelPhrase = (s) => (LEVEL[getLang()] || LEVEL.fr)[s] || (LEVEL[getLang()] || LEVEL.fr).nodata;
export const activityPhrase = (s) => (ACTIVITY[getLang()] || ACTIVITY.fr)[s] || (ACTIVITY[getLang()] || ACTIVITY.fr).nodata;

// percentile -> "higher than 80% of past seasons at the same date"
export function pctPhrase(p) {
  if (p == null || Number.isNaN(p)) return "";
  if (p >= 50) return L(`plus que lors de ${fmt(p, 0)} % des saisons passées à la même date`, `more than in ${fmt(p, 0)}% of past seasons at the same date`);
  return L(`moins que lors de ${fmt(100 - p, 0)} % des saisons passées à la même date`, `less than in ${fmt(100 - p, 0)}% of past seasons at the same date`);
}

// expected / normal -> words
export function ratioPhrase(r) {
  if (r == null || Number.isNaN(r)) return "";
  const x = `×${fmt(r, 1)}`;
  if (r >= 1.5) return L(`nettement plus qu'une année normale (${x})`, `clearly more than in a normal year (${x})`);
  if (r >= 1.1) return L(`un peu plus qu'une année normale (${x})`, `slightly more than in a normal year (${x})`);
  if (r > 0.9) return L("à peu près autant qu'une année normale", "about the same as in a normal year");
  if (r > 0.6) return L(`un peu moins qu'une année normale (${x})`, `slightly fewer than in a normal year (${x})`);
  return L(`nettement moins qu'une année normale (${x})`, `clearly fewer than in a normal year (${x})`);
}

// probability -> "about 1 chance in 4 (26%)"
export function chance(p) {
  if (p == null || Number.isNaN(p)) return "–";
  const pc = Math.round(100 * p);
  if (pc <= 0) return L("presque aucune chance", "almost no chance");
  if (pc <= 50) {
    const n = Math.max(2, Math.round(100 / pc));
    return L(`environ 1 chance sur ${n} (${pc} %)`, `about 1 chance in ${n} (${pc}%)`);
  }
  const k = Math.round(pc / 10);
  return L(`environ ${k} chances sur 10 (${pc} %)`, `about ${k} chances in 10 (${pc}%)`);
}

export function riskAdvice(risk) {
  return {
    high: L("Le risque est élevé : c'est le moment d'agir — renforcer les pare-feux et les patrouilles, et prévenir les villages.",
            "The risk is high: now is the time to act — reinforce firebreaks and patrols, and warn the villages."),
    moderate: L("Le risque est modéré : vérifiez l'état des pare-feux et que les comités de lutte sont prêts à intervenir.",
                "The risk is moderate: check the firebreaks and make sure fire committees are ready to respond."),
    low: L("Rien d'inhabituel : le dispositif habituel suffit.", "Nothing unusual: the usual arrangements are enough."),
    offseason: L("Très peu de feux sont attendus (moins de 10) : pas d'action particulière.",
                 "Very few fires are expected (fewer than 10): no specific action needed."),
  }[risk] || "";
}

// "Kedougou (Kedougou)" -> "Kedougou" (district named after its region)
export const cleanName = (n) => String(n ?? "").replace(/^(.+?) \(\1\)$/, "$1");
// "à Saraya" / "in Saraya"; the regional forecast reads "au Sénégal et en Gambie"
export const inPlace = (name) => L(`à ${esc(cleanName(name))}`, `in ${esc(cleanName(name))}`);
export const inRegion = () => L("au Sénégal et en Gambie", "in Senegal and The Gambia");

// ---------------------------------------------------------------- AI forecast
export function forecastStory(where, b2, b4, until) {
  if (!b2) return [];
  const out = [];
  if (b2.risk === "offseason") {
    out.push(L(`Dans les 2 prochaines semaines${until ? ` (jusqu'au ${esc(until)})` : ""}, très peu de feux sont attendus ${where} : environ ${b(about(b2.mu))}.`,
               `Over the next 2 weeks${until ? ` (until ${esc(until)})` : ""}, very few fires are expected ${where}: about ${b(about(b2.mu))}.`));
  } else {
    out.push(L(`Dans les 2 prochaines semaines${until ? ` (jusqu'au ${esc(until)})` : ""}, on attend environ ${b(about(b2.mu))} feux ${where}, très probablement entre ${fmtInt(b2.lo)} et ${fmtInt(b2.hi)}. C'est ${b(ratioPhrase(b2.ratio))} : à cette période, on en compte d'habitude environ ${about(b2.normal)}.`,
               `Over the next 2 weeks${until ? ` (until ${esc(until)})` : ""}, about ${b(about(b2.mu))} fires are expected ${where}, most likely between ${fmtInt(b2.lo)} and ${fmtInt(b2.hi)}. That is ${b(ratioPhrase(b2.ratio))}: at this time of year there are usually about ${about(b2.normal)}.`));
    if (b2.prob_above != null)
      out.push(L(`Risque que ces deux semaines soient plus actives que 3 années sur 4 : ${b(chance(b2.prob_above))}.`,
                 `Chance that these two weeks will be busier than 3 years out of 4: ${b(chance(b2.prob_above))}.`)
        + (b4 ? " " + L(`Sur 4 semaines : environ ${about(b4.mu)} feux, ${ratioPhrase(b4.ratio)}.`, `Over 4 weeks: about ${about(b4.mu)} fires, ${ratioPhrase(b4.ratio)}.`) : ""));
  }
  out.push(b(esc(riskAdvice(b2.risk))));
  return out.map(typo);
}

// what the model-validation numbers mean
export function skillStory(v) {
  const sk = v?.zone_4wk?.ml?.skill_vs_clim, cov = v?.coverage_4wk, auc = v?.above_normal?.auc_ml;
  if (sk == null) return [];
  const yrs = v.years || [];
  const span = yrs.length ? `${yrs[0]}–${yrs[yrs.length - 1]}` : "";
  const covTxt = cov == null ? "–" : Math.abs(cov - 0.9) < 0.025 ? L("9 fois sur 10", "9 times out of 10") : L(`${fmt(100 * cov, 0)} % du temps`, `${fmt(100 * cov, 0)}% of the time`);
  return [
    L(`Pour vérifier l'IA, on lui a caché chacune des saisons ${span}, une par une, puis on lui a demandé de les prévoir sans les connaître. Résultat :`,
      `To test the AI, each season from ${span} was hidden from it, one at a time, and it was asked to forecast it without having seen it. The result:`),
    `<ul>
      <li>${L(`ses prévisions à 4 semaines sont ${b(fmt(100 * sk, 0) + " %")} plus proches de la réalité que la simple « moyenne des années passées » ;`,
               `its 4-week forecasts are ${b(fmt(100 * sk, 0) + "%")} closer to reality than the simple "average of past years";`)}</li>
      <li>${L(`la vraie valeur tombe dans la fourchette annoncée ${b(covTxt)} ;`, `the real value falls within the announced range ${b(covTxt)};`)}</li>
      ${auc != null ? `<li>${L(`pour repérer à l'avance une quinzaine plus active que la normale, son score est de ${b(fmt(auc, 2))} (0,5 = pur hasard, 1 = parfait) : utile, sans être infaillible ;`,
               `at spotting an above-normal fortnight in advance, it scores ${b(fmt(auc, 2))} (0.5 = pure chance, 1 = perfect): useful, but not infallible;`)}</li>` : ""}
      <li>${L("quand elle annonce « 40 % de chances », l'événement se produit à peu près 4 fois sur 10 : ses probabilités sont honnêtes.",
               "when it says \"40% chance\", the event happens roughly 4 times out of 10: its probabilities are honest.")}</li></ul>`,
    L("FireSync est un outil d'aide à la décision : il indique où le risque est le plus probable, mais il ne connaît pas encore la météo. L'expérience du terrain reste indispensable.",
      "FireSync is a decision-support tool: it shows where the risk is most likely, but it does not yet know the weather. Field experience remains essential."),
  ];
}

// ---------------------------------------------------------------- zone calendar
export function zoneStory(name, cal) {
  const W = cal.week_labels, s = cal.summary || {}, tr = cal.trends || {};
  const wk = (i) => esc(W[i] ?? "–");
  const out = [];
  if (s.onset != null && s.peak != null && s.end != null)
    out.push(L(`${b("Quand ?")} ${inPlace(name).replace(/^à/, "À")}, la saison des feux commence en général vers le ${b(wk(s.onset))}, atteint son maximum vers le ${b(wk(s.peak))} et se termine vers le ${b(wk(s.end))}, soit environ ${s.duration} semaines.`,
               `${b("When?")} ${inPlace(name).replace(/^in/, "In")}, the fire season usually starts around ${b(wk(s.onset))}, peaks around ${b(wk(s.peak))} and ends around ${b(wk(s.end))}: about ${s.duration} weeks.`));
  const c = cal.critical?.["50"];
  if (c)
    out.push(L(`${b("Les semaines à surveiller :")} la moitié des feux de l'année tombe en seulement ${c.weeks} semaines, du ${wk(c.start)} au ${wk(c.end)}. C'est à ce moment que patrouilles, pare-feux et sensibilisation sont les plus utiles.`,
               `${b("The weeks to watch:")} half of the year's fires happen in just ${c.weeks} weeks, from ${wk(c.start)} to ${wk(c.end)}. That is when patrols, firebreaks and awareness campaigns matter most.`));
  const full = (cal.years || []).filter((y) => y.complete && y.total != null);
  if (full.length >= 3) {
    const mean = full.reduce((a, y) => a + y.total, 0) / full.length;
    const rec = full.reduce((m, y) => (y.total > m.total ? y : m), full[0]);
    out.push(L(`${b("Une année ordinaire :")} environ ${b(about(mean))} feux détectés par saison (moyenne de ${full.length} saisons). La saison la plus forte depuis 2000 est ${esc(rec.label)}, avec ${fmtInt(rec.total)} feux.`,
               `${b("An ordinary year:")} about ${b(about(mean))} fires detected per season (average of ${full.length} seasons). The strongest season since 2000 was ${esc(rec.label)}, with ${fmtInt(rec.total)} fires.`));
  }
  const tt = tr.total;
  if (tt && tt.pct_per_decade != null) {
    const pc = tt.pct_per_decade, a = fmt(Math.abs(pc), 0);
    let txt = tt.significant
      ? (pc > 0 ? L(`les feux sont en nette hausse (+${a} % par décennie).`, `fires are clearly increasing (+${a}% per decade).`)
                : L(`les feux sont en nette baisse (−${a} % par décennie).`, `fires are clearly decreasing (−${a}% per decade).`))
      : Math.abs(pc) < 3 ? L("le nombre de feux est resté stable.", "the number of fires has stayed stable.")
      : L(`pas de tendance nette (${pc > 0 ? "légère hausse" : "légère baisse"} de ${a} % par décennie, trop faible pour être certaine).`,
          `no clear trend (a slight ${pc > 0 ? "increase" : "decrease"} of ${a}% per decade, too small to be sure).`);
    const shifts = [];
    const sh = (k, early, late) => { const x = tr[k]; if (x?.significant && Math.abs(x.slope) >= 0.5) shifts.push(x.slope < 0 ? early(Math.abs(x.slope)) : late(x.slope)); };
    // "1,1 semaine" / "2 semaines"; "1.1 weeks" / "1 week"
    const w = (x) => { const v = fmt(x, x < 2 ? 1 : 0); return `${v} ${FR() ? (x < 2 ? "semaine" : "semaines") : (v === "1" || v === "1.0" ? "week" : "weeks")}`; };
    sh("onset", (x) => L(`commence environ ${w(x)} plus tôt par décennie`, `starts about ${w(x)} earlier per decade`),
                (x) => L(`commence environ ${w(x)} plus tard par décennie`, `starts about ${w(x)} later per decade`));
    sh("end", (x) => L(`se termine environ ${w(x)} plus tôt par décennie`, `ends about ${w(x)} earlier per decade`),
              (x) => L(`se termine environ ${w(x)} plus tard par décennie`, `ends about ${w(x)} later per decade`));
    if (shifts.length) txt += " " + L(`En revanche, la saison ${shifts.join(" et ")}.`, `However, the season ${shifts.join(" and ")}.`);
    out.push(`${b(L("Sur 25 ans :", "Over 25 years:"))} ${txt}`);
  }
  const cur = currentStory(cal);
  if (cur) out.push(cur);
  return out.map(typo);
}

export function currentStory(cal) {
  const cur = cal.current;
  if (!cur) return "";
  const W = cal.week_labels, ls = cur.last_status;
  let s = L(`${b(`Saison ${esc(cur.label)} :`)} ${b(fmtInt(cur.cumulative))} feux détectés depuis le début de la saison, ce qui est ${b(levelPhrase(cur.cumulative_status))} pour cette date`,
            `${b(`${esc(cur.label)} season:`)} ${b(fmtInt(cur.cumulative))} fires detected since the season began, which is ${b(levelPhrase(cur.cumulative_status))} for this date`);
  if (cur.clim_cum_median != null && cur.cumulative_status !== "few")
    s += L(` (une saison ordinaire en compte environ ${about(cur.clim_cum_median)} à ce stade)`, ` (an ordinary season has about ${about(cur.clim_cum_median)} at this point)`);
  s += ".";
  if (ls && ls.status !== "few" && ls.value != null)
    s += L(` La dernière semaine connue (${esc(W[ls.fweek])}) a été ${activityPhrase(ls.status)} : ${fmtInt(ls.value)} feux, ${pctPhrase(ls.pct)}.`,
           ` The latest week (${esc(W[ls.fweek])}) was ${activityPhrase(ls.status)}: ${fmtInt(ls.value)} fires, ${pctPhrase(ls.pct)}.`);
  const pk = cal.summary?.peak;
  if (pk != null && cur.last_fweek != null && cur.last_fweek < pk)
    s += L(` Le pic de la saison est encore à venir (en général vers le ${esc(W[pk])}).`, ` The peak of the season is still to come (usually around ${esc(W[pk])}).`);
  return typo(s);
}

// one line on a pro dashboard card
export function zoneCardLine(cumulative, cumStatus, lastStatus) {
  return typo(L(`Depuis le début de la saison : ${b(fmtInt(cumulative))} feux, ${levelPhrase(cumStatus)}. Dernière semaine : ${activityPhrase(lastStatus)}.`,
                `Since the season began: ${b(fmtInt(cumulative))} fires, ${levelPhrase(cumStatus)}. Latest week: ${activityPhrase(lastStatus)}.`));
}

// one line under the status banner of a zone
export function weekLine(cal) {
  const cur = cal.current, ls = cur?.last_status;
  if (!ls) return "";
  const first = ls.status === "few"
    ? L("Trop peu de feux cette semaine-là pour comparer avec le passé.", "Too few fires that week to compare with the past.")
    : L(`Cette semaine-là, ${b(fmtInt(ls.value))} feux ont été détectés : ${pctPhrase(ls.pct)}.`,
        `That week, ${b(fmtInt(ls.value))} fires were detected: ${pctPhrase(ls.pct)}.`);
  return typo(first + " " + L(`Depuis le début de la saison : ${fmtInt(cur.cumulative)} feux, ${levelPhrase(cur.cumulative_status)}.`,
                              `Since the season began: ${fmtInt(cur.cumulative)} fires, ${levelPhrase(cur.cumulative_status)}.`));
}

// ---------------------------------------------------------------- current season (whole region)
export function seasonStory(d, { short = false } = {}) {
  const reg = d.region, W = d.week_labels, ls = reg.last_status || {};
  const out = [];
  out.push(L(`La saison des feux ${esc(reg.label)} a commencé en septembre. Depuis, ${b(fmtInt(reg.cumulative))} feux ont été détectés au Sénégal et en Gambie : c'est ${b(levelPhrase(reg.cumulative_status))} pour cette période de l'année (une saison ordinaire en compte environ ${about(reg.clim_cum_median)} à cette date).`,
             `The ${esc(reg.label)} fire season began in September. Since then, ${b(fmtInt(reg.cumulative))} fires have been detected in Senegal and The Gambia: that is ${b(levelPhrase(reg.cumulative_status))} for this time of year (an ordinary season has about ${about(reg.clim_cum_median)} by this date).`));
  if (ls.value != null)
    out.push(L(`La dernière semaine connue (${esc(W[ls.fweek])}) a été ${b(activityPhrase(ls.status))} : ${fmtInt(ls.value)} feux, ${pctPhrase(ls.pct)}.`,
               `The latest week (${esc(W[ls.fweek])}) was ${b(activityPhrase(ls.status))}: ${fmtInt(ls.value)} fires, ${pctPhrase(ls.pct)}.`));
  const pk = d.summary?.peak;
  if (pk != null && reg.last_fweek != null)
    out.push(reg.last_fweek < pk
      ? L(`Dans une saison ordinaire, le pic arrive vers le ${esc(W[pk])} : le plus gros de la saison est donc encore à venir.`, `In an ordinary season the peak comes around ${esc(W[pk])}: the bulk of the season is still ahead.`)
      : L(`Dans une saison ordinaire, le pic arrive vers le ${esc(W[pk])} : il est normalement passé.`, `In an ordinary season the peak comes around ${esc(W[pk])}: it has normally passed.`));
  if (short) return out.map(typo);
  const rows = (d.regions || []).filter((r) => r.cumulative != null);
  const top = [...rows].sort((a, b2) => b2.cumulative - a.cumulative).slice(0, 3);
  if (top.length)
    out.push(L(`Les régions qui comptent le plus de feux depuis le début : ${top.map((r) => `${b(esc(r.name))} (${fmtInt(r.cumulative)})`).join(", ")}.`,
               `The regions with the most fires so far: ${top.map((r) => `${b(esc(r.name))} (${fmtInt(r.cumulative)})`).join(", ")}.`));
  const hot = rows.filter((r) => r.cumulative_status === "above_p90" || r.cumulative_status === "p75_p90");
  out.push(hot.length
    ? L(`${hot.length > 1 ? `${hot.length} régions sont au-dessus de leur normale` : "Une région est au-dessus de sa normale"} : ${hot.map((r) => esc(r.name)).join(", ")}.`,
        `${hot.length > 1 ? `${hot.length} regions are` : "One region is"} above normal: ${hot.map((r) => esc(r.name)).join(", ")}.`)
    : L("Aucune région n'est au-dessus de sa normale pour l'instant.", "No region is above its normal so far."));
  return out.map(typo);
}
