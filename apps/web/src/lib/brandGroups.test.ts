import { describe, expect, it } from "vitest";
import { canWork, groupBrands, setBrand, setGroup, type BrandRow } from "./brandGroups";

const row = (code: string, group: string | null = null): BrandRow => ({ id: code, code, name: code, group_code: group });
const ALL = ["Ploom GVA3", "Ploom GVA9", "Ploom Pilar", "Cartier", "Valmont", "Nuxe", "Cellcosmet", "Cailler", "Lindt", "Toblerone"].map((c) => row(c));

describe("sélection des marques et boutiques", () => {
  it("regroupe les boutiques Ploom (GVA3, Pilar, GVA9) sous une enseigne ; les autres marques restent seules", () => {
    const g = groupBrands(ALL);
    const ploom = g.find((x) => x.key === "Ploom")!;
    expect(ploom.brands.map((b) => b.label)).toEqual(["GVA3", "GVA9", "Pilar"]);
    expect(g.map((x) => x.key)).toEqual(expect.arrayContaining(["Cartier", "Valmont", "Nuxe", "Cellcosmet", "Cailler", "Lindt", "Toblerone"]));
  });
  it("Zaki : Ploom (toutes les boutiques), Cartier, Valmont, Nuxe, Cellcosmet", () => {
    const g = groupBrands(ALL);
    let b: Record<string, string> = {};
    for (const key of ["Ploom", "Cartier", "Valmont", "Nuxe", "Cellcosmet"]) b = setGroup(b, g.find((x) => x.key === key)!, true);
    expect(Object.keys(b).sort()).toEqual(["Cartier", "Cellcosmet", "Nuxe", "Ploom GVA3", "Ploom GVA9", "Ploom Pilar", "Valmont"]);
    expect(Object.values(b).every((l) => l === "priority")).toBe(true);
  });
  it("boutiques précises : seulement GVA9 et Pilar ; décocher retire la marque", () => {
    let b = setBrand({}, "Ploom GVA9", true); b = setBrand(b, "Ploom Pilar", true, "secondary");
    expect(b).toEqual({ "Ploom GVA9": "priority", "Ploom Pilar": "secondary" });
    expect(setBrand(b, "Ploom GVA9", false)).toEqual({ "Ploom Pilar": "secondary" });
    expect(setBrand(b, "Ploom Pilar", true, "reinforce")["Ploom Pilar"]).toBe("secondary"); // re-cocher ne change pas le niveau
  });
  it("une marque non sélectionnée n'est jamais autorisée", () => {
    const pierre = { Lindt: "priority", Toblerone: "priority", Cailler: "reinforce" };
    expect(canWork(pierre, ["Lindt"])).toBe(true); expect(canWork(pierre, ["Cartier"])).toBe(false);
    expect(canWork(pierre, ["Cellcosmet", "Nuxe"])).toBe(false); expect(canWork(undefined, ["Lindt"])).toBe(false);
  });
});
