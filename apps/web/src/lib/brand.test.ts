import { describe, expect, it } from "vitest";
import { brandIndex, setBrandOrder } from "./brand";

describe("couleurs des marques par entreprise", () => {
  it("les marques d'un catalogue reçoivent des teintes distinctes, dans l'ordre", () => {
    setBrandOrder(["Aurelia Cosmétiques", "Nordique Café", "Solstice Parfums", "Atelier Verre", "Kiosque Mobile"]);
    const n = ["Aurelia Cosmétiques", "Nordique Café", "Solstice Parfums", "Atelier Verre", "Kiosque Mobile"].map(brandIndex);
    expect(new Set(n).size).toBe(5);
    expect(n.every((x) => x >= 1 && x <= 10)).toBe(true); // jamais les teintes neutres (gris) pour une marque du catalogue
  });
  it("les marques historiques gardent leur teinte ; les autres prennent les teintes restantes", () => {
    setBrandOrder(["Cartier", "Nouvelle marque"]);
    expect(brandIndex("Cartier")).toBe(3);
    expect(brandIndex("Nouvelle marque")).not.toBe(3);
    expect(brandIndex("Marque inconnue hors catalogue")).toBeGreaterThan(10);
  });
});
