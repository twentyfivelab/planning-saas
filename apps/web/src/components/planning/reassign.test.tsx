import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { hourRange, longDate, previewConflicts } from "@/lib/reassign";
import type { Assignment } from "@/lib/schedule";
import { ConfirmDialog } from "./useReassign";

const mk = (id: string, emp: string, day: string, start: string, end: string, extra: Partial<Assignment> = {}): Assignment => ({
  assignment_id: id, shift_id: id, slot_key: id, day, site: "GVA3", start, end, presence_minutes: 540, break_minutes: 60, effective_minutes: 480,
  employee_id: emp, employee: emp, locked: false, source: "solver", allocations: { "Ploom GVA3": 480 }, ...extra });

describe("formats de la confirmation", () => {
  it("date longue et horaires en français", () => {
    expect(longDate("2026-11-02")).toBe("Lundi 2 novembre 2026");
    expect(longDate("2026-11-01")).toBe("Dimanche 1er novembre 2026");
    expect(hourRange("06:00:00", "15:00:00")).toBe("06h00 à 15h00");
  });
});

describe("avertissements détectables avant enregistrement", () => {
  const target = mk("t", "mila", "2026-11-02", "06:00:00", "15:00:00");
  it("aucun avertissement si le collaborateur est libre", () => {
    expect(previewConflicts(target, "sabrina", [target, mk("x", "sabrina", "2026-11-05", "06:00:00", "15:00:00")], { "Ploom GVA3": "priority" })).toEqual([]);
  });
  it("chevauchement le même jour", () => {
    const w = previewConflicts(target, "sabrina", [target, mk("x", "sabrina", "2026-11-02", "10:00:00", "19:00:00")]);
    expect(w.map((x) => x.kind)).toContain("overlap");
  });
  it("repos inférieur à 11 h (fermeture puis ouverture) et exactement 11 h autorisé", () => {
    const close = mk("c", "sabrina", "2026-11-01", "12:00:00", "21:00:00");
    expect(previewConflicts(target, "sabrina", [target, close]).map((x) => x.kind)).toContain("rest"); // 21h -> 06h = 9 h
    const ok = mk("o", "sabrina", "2026-11-01", "08:00:00", "19:00:00"); // 19h -> 06h = 11 h
    expect(previewConflicts(target, "sabrina", [target, ok])).toEqual([]);
  });
  it("plus de 6 jours consécutifs", () => {
    const days = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"].map((d, i) => mk(`d${i}`, "sabrina", d, "09:00:00", "18:00:00"));
    expect(previewConflicts(target, "sabrina", [target, ...days]).map((x) => x.kind)).toContain("consecutive");
    expect(previewConflicts(target, "sabrina", [target, ...days.slice(0, 5)]).map((x) => x.kind)).not.toContain("consecutive");
  });
  it("marque non déclarée pour le nouveau collaborateur", () => {
    expect(previewConflicts(target, "jane", [target], { Nuxe: "priority" }).map((x) => x.kind)).toContain("brand");
  });
});

const pending = () => ({ a: mk("t", "mila", "2026-11-02", "06:00:00", "15:00:00"), to: { id: "sabrina", name: "Sabrina", brands: { "Ploom GVA3": "priority" } }, from: { id: "mila", name: "Mila" } });
const dlg = (o: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) => renderToStaticMarkup(
  <ConfirmDialog pending={pending()} all={[pending().a]} saving={false} error="" onCancel={() => {}} onConfirm={() => {}} {...o} />);

describe("modale de confirmation", () => {
  it("affiche ancien et nouveau collaborateur, date, horaires, site, marque, durée effective", () => {
    const html = dlg();
    for (const s of ["Confirmer le remplacement ?", "Mila", "Sabrina", "Lundi 2 novembre 2026", "06h00 à 15h00", "GVA3", "Ploom GVA3", "8 h", "Remplacement de Mila par Sabrina"]) expect(html).toContain(s);
  });
  it("propose Annuler (secondaire) et Confirmer le remplacement (principal), sans « ne plus demander »", () => {
    const html = dlg();
    expect(html).toContain(">Annuler<"); expect(html).toContain(">Confirmer le remplacement<"); expect(html).toContain("btn-primary");
    expect(html.toLowerCase()).not.toContain("plus demander");
    expect(html).not.toContain("<form"); // Entrée n'active que le bouton focalisé, jamais un envoi de formulaire
  });
  it("les boutons sont inactifs pendant l'enregistrement ; l'erreur s'affiche en français avec role=alert", () => {
    const html = dlg({ saving: true });
    expect((html.match(/disabled=""/g) ?? []).length).toBeGreaterThanOrEqual(2); expect(html).toContain("Enregistrement…");
    const err = dlg({ error: "Le remplacement n'a pas pu être enregistré (HTTP 500). L'affectation d'origine est conservée." });
    expect(err).toContain('role="alert"'); expect(err).toContain("d&#x27;origine est conservée");
  });
  it("affiche les avertissements détectés", () => {
    const a = pending().a; const other = mk("x", "sabrina", "2026-11-02", "10:00:00", "19:00:00");
    expect(dlg({ all: [a, other] })).toContain("Chevauchement");
  });
  it("rien n'est rendu quand aucune réaffectation n'est en attente", () => { expect(dlg({ pending: null })).not.toContain("Confirmer le remplacement ?</h2>"); });
});

describe("garde-fou de centralisation", () => {
  it("seul useReassign.tsx appelle l'API de réaffectation (PUT /assignments/…)", () => {
    const root = path.join(__dirname, "..", "..");
    const files: string[] = [];
    const walk = (d: string) => { for (const f of readdirSync(d)) { const p = path.join(d, f); if (statSync(p).isDirectory()) walk(p); else if (/\.(ts|tsx)$/.test(f) && !/\.test\./.test(f)) files.push(p); } };
    walk(root);
    const offenders = files.filter((f) => /assignments\/\$\{[^}]*\}`,\s*\{\s*method:\s*"PUT"/.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => path.basename(f))).toEqual(["useReassign.tsx"]);
  });
});
