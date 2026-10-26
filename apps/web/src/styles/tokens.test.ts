import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/** Contrôle WCAG AA des paires texte/fond déclarées dans tokens.css (clair et sombre). */
const css = readFileSync(path.join(__dirname, "tokens.css"), "utf8");
function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector); const open = css.indexOf("{", start); const close = css.indexOf("\n}", open);
  const out: Record<string, string> = {};
  for (const m of css.slice(open, close).matchAll(/--([\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}
const light = block(":root {"); const dark = { ...light, ...block(':root[data-theme="dark"]') };

function rgba(v: string): [number, number, number, number] {
  const hex = v.match(/^#([0-9a-f]{6})$/i);
  if (hex) { const n = parseInt(hex[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]; }
  const m = v.match(/rgba?\(([^)]+)\)/)!; const p = m[1].split(",").map((x) => parseFloat(x));
  return [p[0], p[1], p[2], p[3] ?? 1];
}
const over = (fg: number[], bg: number[]) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
const lum = (c: number[]) => { const [r, g, b] = c.map((x) => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a: number[], b: number[]) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

for (const [name, t] of [["clair", light], ["sombre", dark]] as const) {
  describe(`contrastes ${name}`, () => {
    // fond de page approximé par le fond de base ; verre = couche translucide posée dessus (cas le plus défavorable : halo le plus proche du texte)
    const base = rgba(t["bg-base"]);
    const surfaces: [string, number[]][] = [["fond", base], ["verre-1", over(rgba(t["glass-1"]), base)], ["verre-2", over(rgba(t["glass-2"]), base)], ["solide-1", rgba(t["solid-1"])], ["solide-2", rgba(t["solid-2"])], ["solide-3", rgba(t["solid-3"])]];
    for (const [sn, bg] of surfaces) {
      for (const k of ["fg", "fg-muted"]) it(`${k} sur ${sn} ≥ 4,5:1`, () => expect(ratio(rgba(t[k]), bg)).toBeGreaterThanOrEqual(4.5));
    }
    it("fg-faint sur solide-1 ≥ 4,5:1 (texte d'aide)", () => expect(ratio(rgba(t["fg-faint"]), rgba(t["solid-1"]))).toBeGreaterThanOrEqual(4.5));
    it("états (ok, warn, bad, info) lisibles sur solide-1", () => { for (const k of ["ok", "warn", "bad", "info", "accent"]) expect(ratio(rgba(t[k]), rgba(t["solid-1"])), k).toBeGreaterThanOrEqual(4.5); });
    it("texte de bouton principal sur accent ≥ 4,5:1", () => expect(ratio(rgba(t["accent-ink"]), rgba(t["accent"]))).toBeGreaterThanOrEqual(4.5));
    for (let n = 1; n <= 10; n++) {
      it(`marque ${n} : encre sur fond doux (sur solide-1) ≥ 4,5:1`, () => expect(ratio(rgba(t[`brand-${n}-ink`]), over(rgba(t[`brand-${n}-soft`]), rgba(t["solid-1"])))).toBeGreaterThanOrEqual(4.5));
    }
  });
}
