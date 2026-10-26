import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BarList, Ring } from "./Charts";
import { Badge, Button, Callout, EmptyState, ErrorState, Field, Input, Progress, Skeleton } from "./primitives";
import { ShiftCard } from "./ShiftCard";
import { resolveTheme } from "./Theme";
import type { Assignment } from "@/lib/schedule";

const A: Assignment = {
  assignment_id: "a1", shift_id: "s1", slot_key: "CN-09|2026-11-05", day: "2026-11-05", site: "Nuxe/Cellcosmet", start: "09:00:00", end: "18:00:00",
  presence_minutes: 540, break_minutes: 60, effective_minutes: 480, employee_id: "e1", employee: "Jane", locked: true, source: "solver",
  allocations: { Cellcosmet: 240, Nuxe: 240 },
};

describe("composants du design system", () => {
  it("ShiftCard : libellé accessible complet (collaborateur, marques, site, horaires, durée, pause, verrouillage, alerte)", () => {
    const html = renderToStaticMarkup(<ShiftCard a={A} alerts={["REST<11h"]} onOpen={() => {}} />);
    for (const s of ["Jane", "Cellcosmet + Nuxe", "09:00 à 18:00", "8 h effectives", "pause 60 min", "verrouillé", "1 alerte"]) expect(html).toContain(s);
    expect(html).toContain('data-locked="true"'); expect(html).toContain('data-alert="true"');
  });
  it("ShiftCard : répartition co-branding 50/50 visible, sans doubler les heures", () => {
    const html = renderToStaticMarkup(<ShiftCard a={A} size="lg" onOpen={() => {}} />);
    expect(html.match(/--share:50/g)).toHaveLength(2);
    expect(html).toContain("8 h · pause 1 h");
    expect(html).not.toContain("16 h");
  });
  it("ShiftCard : mono-marque sans barre de répartition ; site masqué s'il est contenu dans la marque", () => {
    const html = renderToStaticMarkup(<ShiftCard a={{ ...A, site: "GVA3", locked: false, allocations: { "Ploom GVA3": 480 } }} onOpen={() => {}} />);
    expect(html).not.toContain("splitbar"); expect(html).not.toContain("data-locked");
    expect((html.match(/GVA3/g) ?? []).length).toBeGreaterThan(0);
  });
  it("Button icône seule exige un libellé accessible ; Field relie label, aide et erreur", () => {
    expect(renderToStaticMarkup(<Button iconOnly icon="x" label="Fermer" />)).toContain('aria-label="Fermer"');
    const html = renderToStaticMarkup(<Field label="Début" error="Heure invalide">{(p) => <Input {...p} />}</Field>);
    expect(html).toContain("<label"); expect(html).toContain('aria-invalid="true"'); expect(html).toContain('role="alert"'); expect(html).toContain("aria-describedby");
  });
  it("Progress, Ring et BarList exposent des rôles et valeurs lisibles par les lecteurs d'écran", () => {
    expect(renderToStaticMarkup(<Progress value={42} label="Budget" />)).toMatch(/role="progressbar"[^>]*aria-valuenow="42"/);
    expect(renderToStaticMarkup(<Ring value={93.4} label="Budget planifié" />)).toContain('aria-label="Budget planifié : 93 %"');
    const bars = renderToStaticMarkup(<BarList data={[{ key: "a", label: "Cartier", value: 64, max: 64 }, { key: "b", label: "Lindt", value: 0, max: 64 }]} />);
    expect(bars).toContain('role="list"'); expect(bars).toContain('aria-valuenow="64"'); expect(bars).toContain('aria-valuenow="0"');
  });
  it("états : squelette masqué aux lecteurs, vide, erreur avec réessai, callout d'alerte", () => {
    expect(renderToStaticMarkup(<Skeleton />)).toContain('aria-hidden="true"');
    expect(renderToStaticMarkup(<EmptyState title="Aucune version" />)).toContain("Aucune version");
    const err = renderToStaticMarkup(<ErrorState message="HTTP 500" onRetry={() => {}} />);
    expect(err).toContain('role="alert"'); expect(err).toContain("Réessayer");
    expect(renderToStaticMarkup(<Callout kind="bad">x</Callout>)).toContain('role="alert"');
    expect(renderToStaticMarkup(<Badge tone="warn">À renseigner</Badge>)).toContain("badge-warn");
  });
  it("thème : « automatique » suit le système, sinon le choix explicite", () => {
    expect(resolveTheme("system", true)).toBe("dark"); expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light"); expect(resolveTheme("dark", false)).toBe("dark");
  });
});
