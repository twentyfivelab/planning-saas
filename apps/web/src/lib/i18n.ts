import fr from "../../messages/fr.json";

type Messages = Record<string, string>;
const catalogs: Record<string, Messages> = { fr };
let locale = "fr";

export function setLocale(l: string) { if (catalogs[l]) locale = l; }
/** Ajouter une langue = ajouter messages/<code>.json et l'enregistrer dans `catalogs`. */
export function t(key: string): string { return catalogs[locale]?.[key] ?? catalogs.fr[key] ?? key; }
