/** Palette marques : 12 teintes définies dans tokens.css (--brand-N, -soft, -ink) ; 1 à 10 distinctes, 11 et 12 neutres.
 *  Chaque entreprise a ses propres marques : leurs couleurs suivent l'ordre de SON catalogue (`setBrandOrder`), si bien que deux marques
 *  d'une même entreprise ne partagent une teinte qu'au-delà de 10 marques. Les marques historiques gardent leur teinte d'origine. */
export const KNOWN_BRANDS = ["Ploom GVA3", "Ploom GVA9", "Cartier", "Valmont", "Cellcosmet", "Nuxe", "Cailler", "Lindt", "Toblerone", "Ploom Pilar"];
export const BRAND_SLOTS = 12;

let order: string[] = [];
/** Ordre des marques du catalogue de l'entreprise connectée (appelé au chargement de l'application). */
export function setBrandOrder(brands: string[]): void { order = [...brands]; }

export function brandIndex(brand: string): number {
  const i = KNOWN_BRANDS.indexOf(brand);
  if (i >= 0) return i + 1;
  const j = order.indexOf(brand);
  if (j >= 0) {  // teintes encore libres dans ce catalogue (non prises par une marque historique présente), dans l'ordre
    const taken = new Set(order.map((b) => KNOWN_BRANDS.indexOf(b)).filter((k) => k >= 0).map((k) => k + 1));
    const free = Array.from({ length: 10 }, (_, k) => k + 1).filter((k) => !taken.has(k));
    const rank = order.filter((b) => !KNOWN_BRANDS.includes(b)).indexOf(brand);
    return free.length ? free[rank % free.length] : 11 + (rank % 2);
  }
  let h = 0;
  for (const ch of brand) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return 11 + (h % 2); // marque hors catalogue (archivée, inconnue) : teinte neutre
}

/** Variables CSS à poser sur un élément pour le colorer à la marque. */
export function brandVars(brand: string): Record<string, string> {
  const n = brandIndex(brand);
  return { "--c": `var(--brand-${n})`, "--soft": `var(--brand-${n}-soft)`, "--ink": `var(--brand-${n}-ink)` };
}

export const brandColor = (brand: string) => `var(--brand-${brandIndex(brand)})`;
