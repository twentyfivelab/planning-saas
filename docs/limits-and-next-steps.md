# Limites actuelles et prochaines étapes vers la production

## Statut : non commercialisable en l'état (règles légales suisses non exécutées)
| Règle | État |
|---|---|
| Repos quotidien (défaut 11 h) | exécuté, valeur de référence **non validée juridiquement** |
| Maximum de jours consécutifs (défaut 6) | exécuté (règle interne), **non validé** |
| Pauses légales | **non exécuté** |
| Durée maximale du travail (journalière/hebdomadaire) | **non exécuté** |
| Travail de nuit | **non exécuté** |
| Travail du dimanche (autorisations/compensations) | **non exécuté** |
| Jeunes travailleurs, catégories particulières | **non exécuté** |
| Dérogations conventionnelles (CCT) | stockées, **non exécutées** |

Tant que les lignes « non exécuté » ne sont pas implémentées et validées par un spécialiste du droit suisse,
l'application ne doit être ni commercialisée ni utilisée en production.

## Limites
- Les contrats, disponibilités complètes, congés et besoins Lindt/Toblerone ne sont pas fournis : la simulation est
  exploratoire et non publiable ; 1 624 h planifiées sur 1 752 h.
- Hypothèses à confirmer : horaires Cailler (09–18) et Nuxe/Cellcosmet (08-17/09-18/10-19) ; éligibilité marque des
  collaborateurs sans marque indiquée (Ploom) ; poids d'attribution (1,25 / 0,75).
- Effectif requis fixé à 1 par shift ; aucun historique avant la période (jours consécutifs / repos à la frontière).
- Les règles légales (pauses, nuit, dimanche, jeunes travailleurs) ne sont pas implémentées comme règles du solveur.
- Rate-limit en mémoire par processus ; progression d'exécution = statut (pas de % CP-SAT).
- Le redimensionnement d'un shift se fait par formulaire (pas par poignée graphique).
- Pas d'intégration de facturation (table `subscriptions` prête).

## Prochaines étapes
1. Validation juridique et saisie des contrats/disponibilités/congés réels ; besoins Lindt/Toblerone.
2. Règles légales versionnées exécutées par le solveur (pauses, nuit, dimanche, catégories).
3. Rate-limit Redis, purge des sessions, rotation des secrets, SSO/MFA, reverse proxy HTTPS, observabilité.
4. Tests de charge multi-tenant, politique de sauvegarde/PITR, plan de reprise.
5. Poignées de redimensionnement, notifications, application mobile collaborateur.
