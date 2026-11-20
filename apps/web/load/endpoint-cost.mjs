import { request } from "@playwright/test";
import fs from "node:fs";
const pw = fs.readFileSync(process.argv[2], "utf8").trim();
const c = await request.newContext({ baseURL: "http://localhost:8100" });
await c.post("/auth/login", { data: { email: "owner@charge.example", password: pw } });
const pid = (await (await c.post("/periods/ensure", { headers: { "X-CSRF-Token": (await (await c.get("/auth/me")).json()).csrf_token }, data: { year: 2028, month: 9 } })).json()).id;
const paths = ["/auth/me", "/revision", "/periods", "/employees?include_deleted=true", "/budgets", "/clients", "/brands", "/calendar?year=2028&month=9", `/periods/${pid}/schedule`,
  `/periods/${pid}/conflicts`, `/periods/${pid}/sunday-summary`, `/periods/${pid}/integrations`, `/periods/${pid}/params`, `/periods/${pid}/compatibility`,
  `/periods/${pid}/optional-needs`, `/periods/${pid}/regularizations`, `/periods/${pid}/replacement-requests`, "/notifications?unread=true&limit=1", "/site-travel", "/sites", "/catalog?month=2028-09"];
let total = 0;
for (const p of paths) {
  const xs = [];
  for (let i = 0; i < 3; i++) { const r = await c.get(p); xs.push(Number(/app;dur=([\d.]+)/.exec(r.headers()["server-timing"] ?? "")?.[1] ?? -1)); }
  xs.sort((a, b) => a - b); total += xs[1];
  console.log(`${String(xs[1]).padStart(5)} ms  ${p.replace(pid, "{pid}")}`);
}
console.log(`total (médianes) : ${total} ms`);
