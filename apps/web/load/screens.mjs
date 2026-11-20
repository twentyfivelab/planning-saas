// Captures des écrans essentiels (bureau, tablette, téléphone) sur la pile isolée, pour la revue visuelle. Données fictives (entreprise
// « Charge SA » des mesures, ou celle indiquée). Sortie : load/screens/ (non versionné).
//   node load/screens.mjs [email] [fichier-mot-de-passe]
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const WEB = process.env.WEB_URL ?? "http://localhost:3100";
const API = process.env.API_URL ?? "http://localhost:8100";
const email = process.argv[2] ?? "owner@charge.example";
const pw = fs.readFileSync(process.argv[3] ?? "e2e/.auth/load-password.txt", "utf8").trim();
const MONTH = process.env.MONTH ?? "2028-09";
const OUT = path.resolve("load/screens"); fs.mkdirSync(OUT, { recursive: true });
const PAGES = ["/", "/planning", "/generate", "/plannings/new", "/catalog", "/employees", "/budgets", "/history", "/notifications", "/settings"];
const SIZES = { bureau: { width: 1440, height: 900 }, tablette: { width: 1024, height: 1366 }, telephone: { width: 390, height: 844 } };

const browser = await chromium.launch();
for (const [label, vp] of Object.entries(SIZES)) {
  const ctx = await browser.newContext({ viewport: vp });
  const r = await ctx.request.post(`${API}/auth/login`, { data: { email, password: pw } });
  if (!r.ok()) throw new Error(`connexion : ${r.status()}`);
  const page = await ctx.newPage();
  await page.goto(`${WEB}/`); await page.evaluate((m) => { try { localStorage.setItem("planning:month", m); } catch { /* */ } }, MONTH);
  for (const p of PAGES) {
    await page.goto(`${WEB}${p}`);
    await page.locator("main, #contenu, .page").first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(1200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await page.screenshot({ path: path.join(OUT, `${label}${p === "/" ? "-accueil" : p.replaceAll("/", "-")}.png`), fullPage: false });
    console.log(`${label.padEnd(9)} ${p.padEnd(16)} débordement horizontal : ${overflow > 1 ? `${overflow}px ⚠` : "aucun"}`);
  }
  await ctx.close();
}
await browser.close();
