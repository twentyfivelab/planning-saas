/** Bus d'invalidation : toute modification de paramètres (fiche, calendrier, marques, réaffectation…) recharge immédiatement
 *  les données affichées (compteurs, compatibilité, planning) dans tous les écrans montés, sans rechargement de page. */
const EVENT = "planning:data-changed";
export function invalidate(): void { if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT)); }
export function onInvalidate(fn: () => void): () => void {
  window.addEventListener(EVENT, fn);
  return () => window.removeEventListener(EVENT, fn);
}
