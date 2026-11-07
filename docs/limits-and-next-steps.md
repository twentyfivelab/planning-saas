# Limites actuelles et prochaines étapes vers la production

## Statut : non commercialisable en l'état (règles légales suisses non exécutées)
| Règle | État |
|---|---|
| Repos quotidien (défaut 11 h) | exécuté, valeur de référence **à valider** (référentiel juridique) |
| Maximum de jours consécutifs (défaut 6) | exécuté (règle interne), **à valider** |
| Durée maximale hebdomadaire (45 h / 50 h, par régime) | exécutée **si activée** dans le référentiel, semaines à cheval comprises, **à valider** |
| Pauses minimales (art. 15 LTr) | exécutées **si activées** : un shift à la pause insuffisante n'est pas pourvu et le diagnostic le signale, **à valider** |
| Repos réduit à 8 h, durée quotidienne, repos hebdomadaire de 35 h, demi-journée de congé | **non exécutés** |
| Travail de nuit | **non exécuté** |
| Travail du dimanche (autorisations, compensations, repos compensatoires, supplément) | **non exécuté** |
| Travail supplémentaire au sens légal (plafonds 2 h/jour, 140 h/170 h par an) | **non exécuté** |
| Jeunes travailleurs, catégories particulières | **non exécuté** |
| Dérogations conventionnelles (CCT) | stockées, **non exécutées** |

Sources utilisées pour les modèles : SECO, « Durée du travail et du repos » et « Commentaire de la loi sur le travail ». Ces valeurs restent à valider par un responsable juridique.

Tant que les lignes « non exécuté » ne sont pas implémentées et validées par un spécialiste du droit suisse,
l'application ne doit être ni commercialisée ni utilisée en production.

## Limites
- Les limites de jours par semaine sur les semaines à cheval ne sont exactes que si le planning de la période voisine existe ; sinon un
  avertissement (`WEEK_BOUNDARY_HISTORY_MISSING`) l'indique.
- Ploom Pilar : seuls les 2 shifts du dimanche sont fournis (pas de budget ni de besoins hors dimanche) ; ses 80 h de novembre ne sont comptées dans aucun budget.
- Quota de dimanches « objectif exact » : plafond dur, manque pénalisé (jamais un conflit avec une contrainte dure) ; le manque est signalé.
- Budgets : « strict » (défaut, plafond jamais dépassé) ou souple.
- Les contrats, disponibilités complètes, congés et besoins Lindt/Toblerone ne sont pas fournis : la simulation est
  exploratoire et non publiable ; 1 624 h planifiées sur 1 752 h.
- Hypothèses à confirmer : horaires Cailler (09–18) et Nuxe/Cellcosmet (08-17/09-18/10-19) ; éligibilité marque des
  collaborateurs sans marque indiquée (Ploom) ; poids d'attribution (1,25 / 0,75).
- Effectif requis fixé à 1 par shift ; aucun historique avant la période (jours consécutifs / repos à la frontière).
- Les règles légales listées « non exécuté » ci-dessus ne sont pas implémentées comme règles du solveur.
- Rate-limit en mémoire par processus ; progression d'exécution = statut (pas de % CP-SAT).
- Le redimensionnement d'un shift se fait par formulaire (pas par poignée graphique).
- Pas d'intégration de facturation (table `subscriptions` prête).

## Prochaines étapes
1. Validation juridique et saisie des contrats/disponibilités/congés réels ; besoins Lindt/Toblerone.
2. Règles légales versionnées exécutées par le solveur (pauses, nuit, dimanche, catégories).
3. Rate-limit Redis, purge des sessions, rotation des secrets, SSO/MFA, reverse proxy HTTPS, observabilité.
4. Tests de charge multi-tenant, politique de sauvegarde/PITR, plan de reprise.
5. Poignées de redimensionnement, notifications par e-mail ou mobile, application mobile collaborateur.

## Gestion manuelle des shifts depuis le calendrier

- `POST /periods/{id}/manual-assign` attribue un shift libre ou transfère un shift occupé. Le serveur revérifie tout (indisponibilités, marques, repos, jours consécutifs, maximum de jours, quotas de dimanches, horaires autorisés, verrou).
- **Non dérogeables** (toujours bloqués) : un second shift le même jour pour le même collaborateur, collaborateur inactif, shift déjà attribué à la personne. Une règle de l'entreprise (`rest_hours`, `max_consecutive_days`) peut aussi être rendue non dérogeable avec le paramètre `derogable: false`.
- **Dérogables** : toutes les autres alertes, par un rôle propriétaire / administrateur / manager (« Accepter quand même », motif facultatif). Aucune règle légale suisse n'étant validée juridiquement, le repos de 11 h et les 6 jours consécutifs sont dérogeables par défaut et signalés « règle légale ou de référence » : à trancher avec un juriste avant tout usage commercial.
- Les préférences horaires souples n'ajoutent jamais d'alerte. Un shift affecté à la main est verrouillé ; modifier un shift verrouillé demande le même rôle.
- L'historique (`GET /periods/{id}/history`) s'appuie sur le journal d'audit : qui a remplacé qui, quand, motif, dérogation.

## Plusieurs mois et pondérations : limites connues

- Sans planning voisin, les semaines à cheval entre deux mois ne peuvent pas être contrôlées : le manque est signalé, jamais supposé. Générer les mois dans l'ordre améliore la précision.
- Les budgets ne se copient que par action explicite ; les besoins (`staffing_requirements`) sont hebdomadaires : les besoins ponctuels d'un mois précis (animations) se saisissent avec des dates.
- Les poids sont des compromis : le moteur ne garantit pas qu'un poids élevé change le résultat quand une seule solution valide existe ou quand un autre critère domine (couverture).
- La synchronisation entre managers repose sur un flux temps réel (`/events`), avec `/revision` en secours ; les écritures concurrentes sont protégées côté serveur (verrous de ligne, `expected_from`, unicité).
- Les règles légales suisses restent non validées juridiquement : l'application n'est pas commercialisable en l'état.

## Plateforme WFM : ce qui reste à faire

- **Administration SaaS** : pas d'espace « propriétaire de la plateforme » multi-entreprises, ni quotas ni facturation (table `subscriptions` seule). Le rôle `owner` reste propriétaire de SON entreprise.
- **Notifications** : uniquement dans l'application (une par collaborateur et par publication). Pas d'e-mail ni de push.
- **Temps de travail** : prévu, réel et « au-delà du prévu » sont distingués ; la qualification juridique (heures supplémentaires contractuelles ou travail supplémentaire au sens légal) n'est pas calculée.
- **Dimanches** : quotas du mois et équilibre du mois ; l'historique des mois précédents et les repos compensatoires ne sont pas pris en compte.
- **Préférences** : jours de repos, sites, horaires, relations (souples ou strictes). Pas de préférence par type de mission.
- **Missions** : une seule plage horaire et une seule marque par mission (plusieurs sites possibles). Le budget d'heures d'une mission est suivi dans les rapports, pas imposé au moteur (le budget mensuel de la marque, lui, l'est).
- **Co-branding** : moteur et imputations généraux, mais la création d'une animation à deux marques passe par l'API (`/staffing-requirements`) : l'écran « Sites et marques » n'en crée qu'à une marque.
- **Qualifications à échéance** : gérées par l'API et le moteur ; la date d'échéance ne se saisit pas encore dans la fiche.
- **Fonctions accessibles uniquement par l'API** : comptes utilisateurs et périmètre des responsables de marque, journal d'audit complet, effacement et export par personne, congés et disponibilités hebdomadaires, création et suppression d'un collaborateur, animations à plusieurs marques, nouvelle version d'une règle juridique. La liste exacte figure dans le compte rendu de phase.
- **Réoptimisation locale** : un verrou enregistré en dérogation et en conflit avec un autre verrou rend le calcul impossible ; le diagnostic le signale, sans proposer de correction automatique.
- **Performance** : mesurée à 150 collaborateurs, 30 jours, 2 160 shifts. Couverture de 100 % prouvée en quelques secondes ; le niveau « équité et préférences » reste loin de sa borne (coût 197 448 pour une borne de 2 488 en 25 s, 92 287 pour 3 279 en 120 s) : le résultat s'améliore avec le temps de calcul et n'est jamais annoncé comme optimal. Progression affichée par statut, pas en pourcentage. Non testé à plusieurs milliers de collaborateurs ni en charge multi-entreprises.
- **Publication sur les données de démonstration** : refusée tant que des contrats manquent (règle d'origine, conservée). Les contrats se saisissent dans « Collaborateurs ».
- **Protection des données (LPD, RGPD)** : export et anonymisation par personne existent (y compris heures réelles et copies de planning). Le journal d'audit, append-only, conserve les noms d'origine : politique de rétention à décider. Pas d'audit de conformité.
