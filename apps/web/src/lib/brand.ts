/** Palette marques : 10 teintes définies dans tokens.css (--brand-N, -soft, -ink). */
export const KNOWN_BRANDS = ["Ploom GVA3", "Ploom GVA9", "Cartier", "Valmont", "Cellcosmet", "Nuxe", "Cailler", "Lindt", "Toblerone"];
export const BRAND_SLOTS = 10;

export function brandIndex(brand: string): number {
  const i = KNOWN_BRANDS.indexOf(brand);
  if (i >= 0) return i + 1;
  let h = 0;
  for (const ch of brand) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return 1 + (h % BRAND_SLOTS);
}

/** Variables CSS à poser sur un élément pour le colorer à la marque. */
export function brandVars(brand: string): Record<string, string> {
  const n = brandIndex(brand);
  return { "--c": `var(--brand-${n})`, "--soft": `var(--brand-${n}-soft)`, "--ink": `var(--brand-${n}-ink)` };
}

export const brandColor = (brand: string) => `var(--brand-${brandIndex(brand)})`;
