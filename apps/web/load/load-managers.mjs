// Mesures à plusieurs managers sur la pile ISOLÉE (scripts/ops/e2e_stack.sh : web 3100, API 8100, base planning_e2e), jamais sur la base réelle.
// Données entièrement fictives : entreprise « Charge SA », collaborateurs « Collab 01…30 », managers manager01…20@charge.example.
//
//   cd apps/web && node load/load-managers.mjs 5 10 20        (phases à 5, 10 puis 20 sessions distinctes)
//
// Chaque manager a SA session (contexte de navigateur distinct) et réaffecte des shifts depuis l'écran du planning (clic, « Réaffecter à »,
// confirmation). Mesures :
//   - à l'écran : du clic sur « Confirmer le remplacement » à l'apparition du message (« Shift réaffecté… » ou refus « modifié par
//     quelqu'un d'autre »), mesuré DANS la page (MutationObserver, horloge de la page) ;
//   - côté serveur : en-tête Server-Timing de chaque réponse (réaffectation et lectures de fond).
// Pendant chaque phase, une génération tourne sur un AUTRE mois ; une phase supplémentaire la lance sur le MÊME mois.
// Les managers visent volontairement un petit ensemble commun de shifts : des conflits se produisent et doivent être refusés proprement.
// Vérifications finales : un seul titulaire par shift, chaîne des réaffectations acceptées sans perte (chaque acceptation part du titulaire
// laissé par la précédente), compteurs d'heures = somme des affectations, notifications sans doublon. Résultat JSON : load/results/.
import { chromium, request } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const WEB = process.env.WEB_URL ?? "http://localhost:3100";
const API = process.env.API_URL ?? "http://localhost:8100";
const DB = { container: process.env.E2E_DB_CONTAINER ?? "planning-e2e-postgres-1", name: process.env.POSTGRES_DB ?? "planning_e2e" };
const PHASES = process.argv.slice(2).map(Number).filter(Boolean);
const OPS = Number(process.env.OPS ?? 8); // réaffectations par manager et par phase
const SHARED = Number(process.env.SHARED ?? 0.2); // part des opérations sur le petit ensemble de shifts commun à tous (conflits voulus)
const DOMAIN = "charge.example";
const EDIT_MONTH = [2028, 9], GEN_MONTH = [2028, 10];
const PWFILE = path.resolve("e2e/.auth/load-password.txt");
const OUT = path.resolve("load/results");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pct = (xs, p) => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)]; };
const stat = (xs) => ({ n: xs.length, median_ms: pct(xs, 50), p95_ms: pct(xs, 95), max_ms: xs.length ? Math.max(...xs) : null });
const serverMs = (h) => { const m = /app;dur=([\d.]+)/.exec(h ?? ""); return m ? Number(m[1]) : null; };

function psql(sql) {
  const user = execFileSync("docker", ["exec", DB.container, "printenv", "POSTGRES_USER"]).toString().trim();
  return execFileSync("docker", ["exec", DB.container, "psql", "-U", user, "-d", DB.name, "-At", "-F", "|", "-c", sql]).toString().trim();
}

async function client(email, password) {
  const c = await request.newContext({ baseURL: API });
  const r = await c.post("/auth/login", { data: { email, password } });
  if (!r.ok()) { await c.dispose(); return null; }
  const csrf = (await r.json()).csrf_token;
  return { c, csrf, H: { "X-CSRF-Token": csrf } };
}

async function setup() {
  fs.mkdirSync(path.dirname(PWFILE), { recursive: true });
  let pw = fs.existsSync(PWFILE) ? fs.readFileSync(PWFILE, "utf8").trim() : "";
  let o = pw ? await client(`owner@${DOMAIN}`, pw) : null;
  if (!o) {
    pw = randomBytes(12).toString("hex") + "Aa1!";
    fs.writeFileSync(PWFILE, pw, { mode: 0o600 });
    const c = await request.newContext({ baseURL: API });
    const r = await c.post("/auth/register", { data: { tenant_name: "Charge SA", name: "Responsable Charge", email: `owner@${DOMAIN}`, password: pw } });
    if (r.status() !== 201) throw new Error(`inscription : ${r.status()} ${await r.text()}`);
    o = { c, csrf: (await r.json()).csrf_token }; o.H = { "X-CSRF-Token": o.csrf };
    const post = async (p, data) => { const x = await o.c.post(p, { headers: o.H, data }); if (x.status() >= 300) throw new Error(`${p} : ${x.status()} ${await x.text()}`); return x.json(); };
    for (const [code, name] of [["S1", "Site Un"], ["S2", "Site Deux"]]) await post("/catalog/sites", { code, name });
    for (const b of ["Alpha", "Beta", "Gamma"]) await post("/catalog/brands", { name: b });
    await post("/catalog/animations", { site_code: "S1", brand_code: "Alpha", start: "09:00", end: "18:00", weekdays: [0, 1, 2, 3, 4, 5, 6], headcount: 3, from_month: "2028-01" });
    await post("/catalog/animations", { site_code: "S2", brand_code: "Beta", start: "10:00", end: "19:00", weekdays: [0, 1, 2, 3, 4, 5], headcount: 2, from_month: "2028-01" });
    await post("/catalog/animations", { site_code: "S1", brand_code: "Gamma", start: "12:00", end: "21:00", weekdays: [0, 1, 2, 3, 4, 5, 6], headcount: 1, from_month: "2028-01" });
    for (let i = 1; i <= 30; i++) {
      const n = String(i).padStart(2, "0");
      const brands = i % 3 === 0 ? { Alpha: "priority", Beta: "priority", Gamma: "reinforce" } : i % 3 === 1 ? { Alpha: "priority", Gamma: "priority" } : { Beta: "priority", Alpha: "secondary" };
      await post("/employees", { code: `c${n}`, name: `Collab ${n}`, brands });
    }
    for (let i = 1; i <= 20; i++) await post("/users", { email: `manager${String(i).padStart(2, "0")}@${DOMAIN}`, name: `Manager ${String(i).padStart(2, "0")}`, role: "manager", password: pw });
  }
  const ensure = async ([year, month]) => (await (await o.c.post("/periods/ensure", { headers: o.H, data: { year, month } })).json()).id;
  const edit = await ensure(EDIT_MONTH), gen = await ensure(GEN_MONTH);
  const rows = (await (await o.c.get(`/periods/${edit}/schedule`)).json()).assignments;
  if (!rows.length) await generate(o, edit, true);
  return { o, pw, edit, gen };
}

async function generate(o, pid, wait, limit = 30) {
  const r = await o.c.post(`/periods/${pid}/runs`, { headers: { ...o.H, "Idempotency-Key": `load-${Date.now()}-${Math.random()}` }, data: { time_limit_s: limit, confirm_replace: true } });
  if (r.status() !== 202) throw new Error(`génération : ${r.status()} ${await r.text()}`);
  const rid = (await r.json()).run_id;
  const t0 = Date.now();
  const done = (async () => {
    for (;;) {
      const run = await (await o.c.get(`/runs/${rid}`)).json();
      if (!["en_attente", "en_cours"].includes(run.status)) return { ...run, wall_s: (Date.now() - t0) / 1000, started_ms: t0 };
      await sleep(500);
    }
  })();
  return wait ? await done : { rid, done, t0 };
}

// Dans la page : chronomètre du clic de confirmation à l'apparition du résultat à l'écran (même horloge que la page).
const ARM = () => {
  window.__op = new Promise((resolve) => {
    let t0 = null;
    const onClick = (ev) => { const b = ev.target.closest("button"); if (b && /Confirmer le remplacement/.test(b.textContent ?? "")) t0 = performance.now(); };
    document.addEventListener("click", onClick, true);
    const done = (outcome) => { obs.disconnect(); document.removeEventListener("click", onClick, true); resolve({ outcome, ms: t0 === null ? null : performance.now() - t0 }); };
    const obs = new MutationObserver(() => {
      if (t0 === null) return;
      const toasts = [...document.querySelectorAll(".toast")].map((t) => t.textContent ?? "");
      if (toasts.some((t) => t.includes(window.__expect))) return done("accepted");
      const dlg = document.querySelector('dialog[open]');
      if (dlg && /modifié par quelqu.un d.autre/.test(dlg.textContent ?? "")) return done("refused_stale");
      if (dlg && /n'a pas pu être enregistré/.test(dlg.textContent ?? "")) return done("error");
    });
    obs.observe(document.body, { childList: true, subtree: true, characterData: true });
    setTimeout(() => done("timeout"), 20000);
  });
};

async function manager(browser, idx, pw, pid, hot, emps, log, stopAt) {
  const email = `manager${String(idx).padStart(2, "0")}@${DOMAIN}`;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const login = await ctx.request.post(`${API}/auth/login`, { data: { email, password: pw } });
  if (!login.ok()) throw new Error(`connexion ${email} : ${login.status()}`);
  const page = await ctx.newPage();
  let sent = null; // corps réellement envoyé par l'écran (titulaire affiché, nouveau titulaire)
  page.on("request", (r) => { if (r.method() === "PUT" && r.url().includes("/assignments/")) { try { sent = { aid: r.url().split("/assignments/")[1].split("?")[0], ...JSON.parse(r.postData() ?? "{}") }; } catch { /* */ } } });
  let answer = null; // réponse du serveur à la réaffectation de l'opération en cours
  page.on("response", (r) => {
    const u = r.url();
    if (r.request().method() === "PUT" && u.includes("/assignments/")) {
      const tm = r.request().timing(); // ms depuis le début de la requête : attente dans le navigateur (file de connexions), puis réponse
      answer = { status: r.status(), ms: serverMs(r.headers()["server-timing"]), done_at: Date.now(), queued_ms: tm.requestStart >= 0 ? tm.requestStart : null,
                 response_ms: tm.responseStart >= 0 ? tm.responseStart : null };
      log.server.push({ kind: "reassign", ...answer });
    }
  });
  await page.goto(`${WEB}/planning`);
  await page.evaluate(([y, m]) => { try { localStorage.setItem("planning:month", `${y}-${String(m).padStart(2, "0")}`); } catch { /* */ } }, EDIT_MONTH);
  // pas d'attente « réseau au repos » : avec plusieurs managers, les actualisations temps réel ne s'arrêtent jamais (c'est normal)
  await page.reload();
  try { await page.getByRole("region", { name: /Planning général/ }).locator(".shift").first().waitFor({ timeout: 60000 }); }
  catch { log.page_load_failed = (log.page_load_failed ?? 0) + 1; stopAt.v = Math.min(stopAt.v, Date.now()); await ctx.close(); return; }
  // lectures de fond (autres écrans d'un manager) pendant toute la phase, sur la même session
  const bg = (async () => {
    while (Date.now() < stopAt.v) {
      for (const p of [`/periods/${pid}/schedule`, `/periods/${pid}/conflicts`]) {
        const r = await ctx.request.get(`${API}${p}`);
        log.server.push({ kind: p.endsWith("schedule") ? "schedule" : "conflicts", status: r.status(), ms: serverMs(r.headers()["server-timing"]) });
      }
      await sleep(4000 + Math.random() * 2000); // autre écran consulté de temps en temps (rythme réaliste)
    }
  })();
  for (let k = 0; k < OPS; k++) {
    const rows = (await (await ctx.request.get(`${API}/periods/${pid}/schedule`)).json()).assignments;
    const pool = Math.random() < SHARED ? hot.shared : hot.own[idx - 1];
    const aid = pool[Math.floor(Math.random() * pool.length)];
    const a = rows.find((r) => r.assignment_id === aid);
    if (!a || a.locked) { log.ops.push({ manager: idx, outcome: "skipped" }); continue; }
    const busy = new Set(rows.filter((r) => r.day === a.day).map((r) => r.employee_id));
    const free = emps.filter((e) => !busy.has(e.id) && Object.keys(a.allocations).every((b) => b in e.brands));
    if (!free.length) { log.ops.push({ manager: idx, outcome: "skipped" }); continue; }
    const to = free[Math.floor(Math.random() * free.length)];
    try {
      const card = page.getByRole("region", { name: /Planning général/ }).locator(`.shift[data-assignment="${aid}"]`);
      // l'écran d'un manager peut avoir jusqu'à 2,5 s de retard sur l'API (rechargements regroupés) : shift pas encore affiché = non tenté
      if (!(await card.count())) { log.ops.push({ manager: idx, outcome: "skipped", reason: "pas encore affiché" }); continue; }
      sent = null; answer = null;
      await page.evaluate((name) => { window.__expect = `Shift réaffecté à ${name}`; }, to.name);
      await page.evaluate(ARM);
      await card.click({ timeout: 5000 });
      await page.getByLabel("Réaffecter à").selectOption(to.id, { timeout: 4000 });
      await page.getByRole("button", { name: "Réaffecter", exact: true }).click({ timeout: 4000 });
      const dlg = page.getByRole("dialog", { name: "Confirmer le remplacement ?" });
      const t_req = Date.now();
      await dlg.getByRole("button", { name: "Confirmer le remplacement" }).click({ timeout: 4000 });
      const res = await page.evaluate(() => window.__op);
      let seen = null;
      if (res.outcome === "timeout") seen = await page.evaluate(() => ({ dialog: (document.querySelector('dialog[open]')?.textContent ?? "").slice(0, 300),
        toasts: [...document.querySelectorAll(".toast")].map((t) => (t.textContent ?? "").slice(0, 120)) }));
      log.ops.push({ manager: idx, aid: sent?.aid ?? aid, expected: sent?.expected_employee_id ?? null, to: sent?.employee_id ?? to.id, outcome: res.outcome,
                     screen_ms: res.ms, at: t_req, sent: Boolean(sent), server_status: answer?.status ?? null, server_ms: answer?.ms ?? null,
                     queued_ms: answer?.queued_ms ?? null, response_ms: answer?.response_ms ?? null, done_at: answer?.done_at ?? null, seen });
      if (res.outcome !== "accepted") await page.keyboard.press("Escape").catch(() => {});
    } catch (e) {
      log.ops.push({ manager: idx, aid: sent?.aid ?? aid, expected: sent?.expected_employee_id ?? null, to: sent?.employee_id ?? to.id, outcome: "ui_error",
                     server_status: answer?.status ?? null, done_at: answer?.done_at ?? null, error: String(e).slice(-1400) });
    }
    await page.keyboard.press("Escape").catch(() => {});
    await sleep(300 + Math.random() * 700);
  }
  stopAt.v = Math.min(stopAt.v, Date.now());
  await bg;
  await ctx.close();
}

function chainCheck(ops, startHolder, finalHolder) {
  // dans l'ordre des réponses du serveur (qui sérialise les modifications d'un même shift) : chaque acceptation part du titulaire laissé par
  // la précédente (sinon : écrasement silencieux) ; une demande dont le résultat est déjà en place (même titulaire) est sans effet (lot 1) ;
  // le titulaire final = celui de la dernière acceptation
  const byAid = {};
  for (const o of ops.filter((x) => x.server_status === 200)) (byAid[o.aid] ??= []).push(o);
  const problems = [];
  for (const [aid, list] of Object.entries(byAid)) {
    let holder = startHolder[aid];
    for (const o of list.sort((a, b) => (a.done_at ?? 0) - (b.done_at ?? 0))) {
      if (o.to === holder) continue;
      if (o.expected !== holder) { problems.push({ aid, holder, op: [o.expected, o.to], manager: o.manager }); }
      holder = o.to;
    }
    if (finalHolder[aid] !== holder) problems.push({ aid, expected_final: holder, final: finalHolder[aid] ?? null });
  }
  return problems;
}

function holders(pid) {
  const out = {};
  for (const line of psql(`select a.id, a.employee_id from assignments a where a.period_id = '${pid}'`).split("\n").filter(Boolean)) {
    const [id, e] = line.split("|"); out[id] = e;
  }
  return out;
}

async function phase(n, env, browser, sameMonthGeneration = false) {
  const { o, pw, edit, gen } = env;
  const emps = (await (await o.c.get("/employees")).json()).filter((e) => e.active !== false && !e.deleted_at);
  const rows = (await (await o.c.get(`/periods/${edit}/schedule`)).json()).assignments.filter((a) => !a.locked);
  // petit ensemble commun de shifts visés par tous : des conflits se produisent forcément
  const mixed = rows.sort(() => Math.random() - 0.5).map((a) => a.assignment_id);
  const shared = mixed.slice(0, 6);
  const own = Array.from({ length: n }, (_, i) => mixed.slice(6 + i * 8, 6 + (i + 1) * 8));  // 8 shifts propres à chaque manager
  const hot = { shared, own };
  const start = holders(edit);
  const notifBefore = Number(psql(`select count(*) from notifications`));
  const log = { ops: [], server: [] };
  const stopAt = { v: Date.now() + 10 * 60_000 };
  const g = await generate(o, sameMonthGeneration ? edit : gen, false);
  const t0 = Date.now();
  await Promise.all(Array.from({ length: n }, (_, i) => manager(browser, i + 1, pw, edit, hot, emps, log, stopAt)));
  const wall = (Date.now() - t0) / 1000;
  const run = await g.done;
  const end = holders(edit);
  // cohérence : un seul titulaire par shift ; chaîne sans perte ; compteurs ; notifications
  const dup = Number(psql(`select count(*) from (select shift_id from assignments where period_id = '${edit}' group by shift_id having count(*) > 1) d`));
  const lost = sameMonthGeneration ? [] : chainCheck(log.ops, start, end);
  // vérification qui fait foi : journal d'audit du serveur. Pour chaque shift réaffecté pendant la phase, chaque changement part du titulaire
  // laissé par le précédent (aucun écrasement silencieux) et le titulaire final est celui du dernier changement.
  const since = new Date(t0 - 2000).toISOString();
  const audit = psql(`select entity_id, detail->'from'->>'id', detail->'to'->>'id' from audit_logs where action = 'assignment.reassign' and created_at >= '${since}' order by entity_id, created_at, id`)
    .split("\n").filter(Boolean).map((l) => l.split("|"));
  const auditBreaks = [];
  const byA = {};
  for (const [aid, from, to] of audit) (byA[aid] ??= []).push([from, to]);
  for (const [aid, chain] of Object.entries(byA)) {
    let h = start[aid] ?? chain[0][0];
    for (const [from, to] of chain) { if (from !== h) auditBreaks.push({ aid, holder: h, from, to }); h = to; }
    if (!sameMonthGeneration && end[aid] !== h) auditBreaks.push({ aid, last_to: h, final: end[aid] ?? null });
  }
  const overwritten = sameMonthGeneration
    ? log.ops.filter((x) => x.server_status === 200 && x.at > g.t0 && x.at < g.t0 + run.wall_s * 1000 && end[x.aid] !== x.to
      && !log.ops.some((y) => y.server_status === 200 && y.aid === x.aid && y.at > x.at)).length
    : null;
  const dbMin = {};
  for (const line of psql(`select a.employee_id, sum(s.effective_minutes) from assignments a join shifts s on s.id = a.shift_id where a.period_id = '${edit}' group by 1`).split("\n").filter(Boolean)) {
    const [e, mi] = line.split("|"); dbMin[e] = Number(mi);
  }
  let counterMismatch = 0;
  const month = `${EDIT_MONTH[0]}-${String(EDIT_MONTH[1]).padStart(2, "0")}`;
  for (const e of emps) {
    const t = (await (await o.c.get(`/employees/${e.id}/month?month=${month}`)).json()).totals.effective_minutes;
    if (t !== (dbMin[e.id] ?? 0)) counterMismatch++;
  }
  const notifAfter = Number(psql(`select count(*) from notifications`));
  const notifDup = Number(psql(`select count(*) from (select user_id, kind, title, body from notifications where created_at > now() - interval '15 minutes' group by 1,2,3,4 having count(*) > 1) d`));
  const screen = log.ops.filter((x) => x.screen_ms != null && (x.outcome === "accepted" || x.outcome === "refused_stale")).map((x) => x.screen_ms);
  const acc = log.ops.filter((x) => x.outcome === "accepted" && x.screen_ms != null).map((x) => x.screen_ms);
  const srv = (k) => log.server.filter((x) => x.kind === k && x.ms != null).map((x) => x.ms);
  const count = (k) => log.ops.filter((x) => x.outcome === k).length;
  return {
    managers: n, same_month_generation: sameMonthGeneration, wall_s: wall,
    ops: { attempted: log.ops.length, accepted: count("accepted"), refused_stale: count("refused_stale"), skipped: count("skipped"), errors: count("error"), ui_errors: count("ui_error"), timeouts: count("timeout"),
           server_200: log.ops.filter((x) => x.server_status === 200).length, server_409: log.ops.filter((x) => x.server_status === 409).length,
           server_other: log.ops.filter((x) => x.server_status && ![200, 409].includes(x.server_status)).length, not_sent: log.ops.filter((x) => x.sent === false).length },
    timeout_samples: log.ops.filter((x) => x.outcome === "timeout").slice(0, 4).map((x) => ({ sent: x.sent, status: x.server_status, seen: x.seen })),
    screen_confirmation: stat(acc), browser_queue: stat(log.ops.filter((x) => x.queued_ms != null).map((x) => x.queued_ms)),
    request_to_response: stat(log.ops.filter((x) => x.response_ms != null).map((x) => x.response_ms)), screen_any_result: stat(screen), accepted_under_2s_pct: acc.length ? Math.round((1000 * acc.filter((x) => x < 2000).length) / acc.length) / 10 : null,
    server: { reassign: stat(srv("reassign")), schedule: stat(srv("schedule")), conflicts: stat(srv("conflicts")),
              http_5xx: log.server.filter((x) => x.status >= 500).length, reassign_409: log.server.filter((x) => x.kind === "reassign" && x.status === 409).length },
    generation: { month: sameMonthGeneration ? "même mois" : "autre mois", status: run.status, wall_s: run.wall_s, saved: run.save?.outcome ?? null },
    page_load_failed: log.page_load_failed ?? 0,
    consistency: { duplicate_holders: dup, audit_changes: audit.length, audit_chain_breaks: auditBreaks, lost_updates_client_view: lost, overwritten_by_generation: overwritten, counter_mismatches: counterMismatch, notifications_created: notifAfter - notifBefore, notification_duplicates: notifDup },
    ui_error_samples: log.ops.filter((x) => x.outcome === "ui_error").slice(0, 3).map((x) => x.error),
  };
}

function environment() {
  let docker = {};
  try { const i = JSON.parse(execFileSync("docker", ["info", "--format", "{{json .}}"]).toString()); docker = { cpus: i.NCPU, memory_gb: Math.round(i.MemTotal / 1e9), server: i.ServerVersion }; } catch { /* */ }
  return { machine: os.cpus()[0]?.model, cores: os.cpus().length, memory_gb: Math.round(os.totalmem() / 1e9), os: `${os.type()} ${os.release()}`, node: process.version, docker,
           load_avg_start: os.loadavg().map((x) => Math.round(x * 10) / 10), web: WEB, api: API, database: DB.name };
}

const env = await setup();
const browser = await chromium.launch();
const out = { at: new Date().toISOString(), environment: environment(), ops_per_manager: OPS, phases: [] };
for (const n of PHASES) {
  const r = await phase(n, env, browser);
  out.phases.push(r);
  fs.mkdirSync(OUT, { recursive: true }); fs.writeFileSync(path.join(OUT, `managers-${out.at.replace(/[:.]/g, "-")}.json`), JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ managers: n, page_load_failed: r.page_load_failed, ops: r.ops, screen: r.screen_confirmation, under2s: r.accepted_under_2s_pct, queue: r.browser_queue, response: r.request_to_response, server: r.server, consistency: r.consistency }));
}
if (process.env.SAME_MONTH !== "0") {
  const r = await phase(Math.min(10, Math.max(...PHASES, 5)), env, browser, true);
  out.phases.push(r);
  console.log(JSON.stringify({ same_month: true, ops: r.ops, generation: r.generation, consistency: r.consistency }));
}
out.environment.load_avg_end = os.loadavg().map((x) => Math.round(x * 10) / 10);
await browser.close();
fs.mkdirSync(OUT, { recursive: true });
const file = path.join(OUT, `managers-${out.at.replace(/[:.]/g, "-")}.json`);
fs.writeFileSync(file, JSON.stringify(out, null, 1));
console.log(`Résultats : ${file}`);
