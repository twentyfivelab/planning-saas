// Charge SANS navigateur (pile isolée) : même trafic qu'un écran de manager — une réaffectation toutes les ~3 s (titulaire affiché envoyé), et,
// au plus toutes les 2,5 s, la relecture des vues qui dépendent du planning (rafraîchissement ciblé). Sert à séparer la capacité du
// serveur de la limite de la machine de test (navigateurs, Docker et API sur le même portable). Données fictives « Charge SA ».
//   node load/api-load.mjs 10 20 40      (sessions distinctes)
import { request } from "@playwright/test";
import fs from "node:fs";

const API = process.env.API_URL ?? "http://localhost:8100";
const pw = fs.readFileSync("e2e/.auth/load-password.txt", "utf8").trim();
const DURATION = Number(process.env.DURATION ?? 45) * 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pct = (xs, p) => { const s = [...xs].sort((a, b) => a - b); return s.length ? Math.round(s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)]) : null; };
const errors = { timeout: 0, other: 0 };
async function safe(fn) { try { return await fn(); } catch (e) { if (/Timeout/.test(String(e))) errors.timeout++; else errors.other++; return null; } }
const srv = (r) => Number(/app;dur=([\d.]+)/.exec(r.headers()["server-timing"] ?? "")?.[1] ?? NaN);

async function session(i) {
  const c = await request.newContext({ baseURL: API });
  const r = await c.post("/auth/login", { data: { email: `manager${String(((i - 1) % 20) + 1).padStart(2, "0")}@charge.example`, password: pw } });
  return { c, H: { "X-CSRF-Token": (await r.json()).csrf_token } };
}

async function run(n) {
  const o = await session(1);
  const pid = (await (await o.c.post("/periods/ensure", { headers: o.H, data: { year: 2028, month: 9 } })).json()).id;
  const emps = await (await o.c.get("/employees")).json();
  const VIEWS = [`/periods/${pid}/schedule`, `/periods/${pid}/conflicts`, `/periods/${pid}/sunday-summary`, `/periods/${pid}/optional-needs`,
    `/periods/${pid}/regularizations`, `/periods/${pid}/replacement-requests`, `/periods/${pid}/integrations`, `/periods/${pid}/compatibility`, "/periods"];
  const res = { put: [], putSrv: [], view: [], viewSrv: [], status: {} };
  const stop = Date.now() + DURATION;
  const sessions = await Promise.all(Array.from({ length: n }, (_, i) => session(i + 1)));
  await Promise.all(sessions.map(async (s, i) => {
    let lastRefresh = 0;
    while (Date.now() < stop) {
      const sch = await safe(() => s.c.get(`/periods/${pid}/schedule`, { timeout: 15000 }));
      if (!sch) { await sleep(1000); continue; }
      const rows = (await sch.json()).assignments.filter((a) => !a.locked);
      const a = rows[(i * 7 + Math.floor(Math.random() * 8)) % rows.length];
      const busy = new Set(rows.filter((x) => x.day === a.day).map((x) => x.employee_id));
      const free = emps.filter((e) => !busy.has(e.id) && Object.keys(a.allocations).every((b) => b in e.brands));
      if (free.length) {
        const t = Date.now();
        const r = await safe(() => s.c.put(`/assignments/${a.assignment_id}`, { headers: s.H, timeout: 15000, data: { employee_id: free[Math.floor(Math.random() * free.length)].id, expected_employee_id: a.employee_id } }));
        res.put.push(Date.now() - t);  // un délai dépassé compte comme une attribution non confirmée en moins de 2 s
        if (r) { res.putSrv.push(srv(r)); res.status[r.status()] = (res.status[r.status()] ?? 0) + 1; }
      }
      if (Date.now() - lastRefresh > 2500) {  // rafraîchissement ciblé (annonces des autres managers regroupées)
        lastRefresh = Date.now();
        const t = Date.now();
        const rs = await Promise.all(VIEWS.map((v) => safe(() => s.c.get(v, { timeout: 15000 }))));
        res.view.push(Date.now() - t); rs.filter(Boolean).forEach((r) => { res.viewSrv.push(srv(r)); res.status[r.status()] = (res.status[r.status()] ?? 0) + 1; });
      }
      await sleep(2500 + Math.random() * 1000);
    }
  }));
  const ok = res.put.filter((x) => x < 2000).length;
  return { sessions: n, reassign: { n: res.put.length, median_ms: pct(res.put, 50), p95_ms: pct(res.put, 95), under_2s_pct: Math.round((1000 * ok) / Math.max(1, res.put.length)) / 10,
           server_median_ms: pct(res.putSrv.filter(Number.isFinite), 50), server_p95_ms: pct(res.putSrv.filter(Number.isFinite), 95) },
           refresh: { n: res.view.length, median_ms: pct(res.view, 50), p95_ms: pct(res.view, 95) }, status: res.status, errors: { ...errors } };
}

for (const n of process.argv.slice(2).map(Number)) { errors.timeout = 0; errors.other = 0; console.log(JSON.stringify(await run(n))); }
