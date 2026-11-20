/** Bus d'invalidation : toute modification de paramètres (fiche, calendrier, marques, réaffectation…) recharge immédiatement
 *  les données affichées (compteurs, compatibilité, planning) dans tous les écrans montés, sans rechargement de page.
 *  Portée « planning » (modifications d'affectations ou de shifts faites par un AUTRE manager, annoncées en temps réel) : seules les vues
 *  qui en dépendent sont relues — mesure à plusieurs managers du 20/11 : relire toutes les vues à chaque annonce saturait l'API. */
const EVENT = "planning:data-changed";
export type Scope = "all" | "planning";

/** Actions journalisées qui ne touchent QUE le contenu du planning (affectations, shifts, besoins placés, remplacements). */
export const PLANNING_ACTIONS = /^(assignment|shift|need|replacement|regularization)\./;
/** Vues qui dépendent du contenu du planning (les référentiels, fiches, paramètres et calendrier n'en dépendent pas). */
export const PLANNING_VIEWS = /\/(schedule|conflicts|compatibility|sunday-summary|optional-needs|regularizations|replacement-requests|integrations|day-shifts|summary|month|notifications|revision|me\/|periods(\?|$))/;

export function invalidate(scope: Scope = "all"): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent<Scope>(EVENT, { detail: scope }));
}
export function onInvalidate(fn: (scope: Scope) => void): () => void {
  const h = (e: Event) => fn(((e as CustomEvent<Scope>).detail as Scope | undefined) ?? "all");
  window.addEventListener(EVENT, h);
  return () => window.removeEventListener(EVENT, h);
}
