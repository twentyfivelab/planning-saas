export type BrandRow = { id: string; code: string; name: string; group_code: string | null };
export type Level = "priority" | "secondary" | "reinforce";
export const LEVEL_LABEL: Record<Level, string> = { priority: "Prioritaire", secondary: "Secondaire", reinforce: "Renfort" };
export const LEVELS = Object.keys(LEVEL_LABEL) as Level[];

export type BrandGroup = { key: string; label: string; brands: { code: string; label: string }[] };

/** Regroupe les marques par enseigne : « Ploom GVA3 / Pilar / GVA9 » sous « Ploom » (boutiques), les autres une par une. */
export function groupBrands(brands: BrandRow[]): BrandGroup[] {
  const map = new Map<string, BrandGroup>();
  for (const b of [...brands].sort((x, y) => x.code.localeCompare(y.code, "fr"))) {
    const [first, ...rest] = b.code.split(" ");
    const grouped = rest.length > 0 && brands.filter((x) => x.code.startsWith(first + " ")).length > 1;
    const key = grouped ? first : b.code;
    const g = map.get(key) ?? { key, label: grouped ? first : b.name, brands: [] };
    g.brands.push({ code: b.code, label: grouped ? rest.join(" ") : b.name });
    map.set(key, g);
  }
  return [...map.values()];
}

export function setBrand(cur: Record<string, string>, code: string, on: boolean, level: Level = "priority"): Record<string, string> {
  const next = { ...cur };
  if (on) next[code] = next[code] ?? level; else delete next[code];
  return next;
}
export function setGroup(cur: Record<string, string>, g: BrandGroup, on: boolean): Record<string, string> {
  let next = { ...cur };
  for (const b of g.brands) next = setBrand(next, b.code, on);
  return next;
}
/** Une marque est-elle autorisée pour ce collaborateur ? (toutes les marques d'un shift doivent l'être) */
export const canWork = (brands: Record<string, string> | undefined, shiftBrands: string[]) => !!brands && shiftBrands.every((b) => b in brands);
