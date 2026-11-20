# Mesures à plusieurs managers (lot 3, 20/11/2026)

**Objectif initial** : avec 10 managers simultanés, 95 % des attributions confirmées à l'écran en moins de 2 secondes.

## Méthode

- **Environnement** : pile isolée (`scripts/ops/e2e_stack.sh`, base `planning_e2e`, ports 3100 / 8100). Jamais la base réelle.
- **Données fictives** : entreprise « Charge SA », 30 collaborateurs « Collab 01…30 », 3 marques, 2 sites, environ 300 shifts par mois, 20 comptes manager distincts.
- **Machine** : un seul portable, Apple M4, 10 cœurs, 16 Go, macOS (Darwin 24.6). Docker dispose de 10 processeurs et 8 Go. Les navigateurs de test, Docker, l'API, la base et le générateur de charge s'y partagent les ressources (voir « Limites »).
- **Mesure à l'écran** (`apps/web/load/load-managers.mjs`) :
  - chaque manager a sa propre session, dans un navigateur distinct, et réaffecte des shifts depuis le planning (clic sur le shift, « Réaffecter à », « Confirmer le remplacement ») ;
  - temps mesuré **dans la page** : du clic de confirmation à l'apparition du message (« Shift réaffecté… » ou refus « modifié par quelqu'un d'autre ») ;
  - 8 réaffectations par manager et par phase ;
  - 80 % des opérations portent sur les shifts propres au manager, 20 % sur 6 shifts communs à tous (conflits voulus) ;
  - lectures de fond toutes les 4 à 6 s ;
  - **une génération tourne pendant chaque phase** sur un autre mois ; une phase supplémentaire la lance sur le **même** mois.
- **Temps serveur** : en-tête `Server-Timing` (traitement, et attente éventuelle dans la file « queue »).
- **Charge sans navigateur** (`apps/web/load/api-load.mjs`) : même trafic qu'un écran, par l'API, sans rendu. Elle sépare la capacité du serveur de la limite de la machine de test.
- **Cohérence, vérifiée après chaque phase** :
  - un seul titulaire par shift ;
  - **journal d'audit du serveur** : chaque réaffectation part du titulaire laissé par la précédente, et le titulaire final est celui du dernier changement ;
  - compteurs d'heures de chaque collaborateur égaux à la somme des affectations ;
  - notifications sans doublon.

## Goulots trouvés et corrigés (chacun démontré, puis remesuré)

| # | Constat (preuve) | Cause | Correction |
|---|---|---|---|
| 1 | 10 managers : des lectures à 30 s côté serveur, phase interrompue | API en **un seul processus** ; à chaque modification, chaque écran relisait toutes ses vues : charge proportionnelle au **carré** du nombre de managers (calcul : environ 144 ms de calcul serveur par relecture complète) | API en **4 processus** ; annonces des autres managers **regroupées** (au plus une relecture toutes les 2,5 s par écran) ; limitation des tentatives de connexion partagée par Redis |
| 2 | 28 requêtes SQL par lecture en moyenne ; les mêmes vues recalculées par chaque écran | Chaque vue reconstruit le problème du mois | **Cache des lectures d'affichage** par révision (journal d'audit), durée de vie 10 s, clé incluant rôle et périmètre (test : le responsable de marque ne voit jamais la vue d'un manager) ; conflits calculés une fois par révision, réutilisés entre la réponse d'une modification et les relectures |
| 3 | Après une modification d'affectation, 17 vues relues, dont compatibilité, paramètres, calendrier, référentiels | Relecture non ciblée | **Rafraîchissement ciblé** : une modification du contenu du planning ne fait relire que les vues qui en dépendent (test unitaire de la règle) |
| 4 | 40 sessions sans navigateur : 436 délais dépassés, **processeur de l'API au repos**, 373 erreurs « QueuePool limit reached » | **Interblocage** entre le pool de connexions (15 par processus) et le pool de threads (40) : des connexions gardées par des requêtes qui attendaient un thread, pendant que tous les threads attendaient une connexion | **Limite de requêtes simultanées** par processus, avant tout thread et toute connexion (12 ; les autres attendent leur tour, attente publiée) ; pool dimensionné (16 par processus, 64 au plus, sous la limite de PostgreSQL) |
| 5 | Génération du même mois : une modification faite pendant le calcul était écrasée sans avertissement (démontré par un test qui échoue sans la correction) | L'enregistrement remplaçait le planning d'après l'état lu au démarrage | Shifts puis affectations verrouillés à l'enregistrement, état comparé à celui du démarrage ; s'il a changé, rien n'est écrasé et la raison est donnée (« relancez le calcul ») |

## Résultats

### À l'écran (navigateurs réels, une génération en cours pendant chaque phase), configuration finale

| Managers | Passage | Attributions confirmées < 2 s | Médiane | 95e centile | Max | Refus corrects (conflit) | Erreurs serveur | Délais dépassés | Écrans non chargés | Erreurs d'interface du script |
|---|---|---|---|---|---|---|---|---|---|---|
| 5 | — | **100 %** | 180 ms | 544 ms | 636 ms | 0 | 0 | 0 | 0 | 0 |
| 10 | A | 83,8 % | 1,14 s | 2,73 s | 3,87 s | 0 | 0 | 0 | 0 | 6 |
| 10 | B | **98,4 %** | 346 ms | 1,35 s | 2,08 s | 2 | 0 | 0 | 0 | 16 |
| 10 | C | **100 %** | 201 ms | 1,27 s | 1,51 s | 3 | 0 | 0 | 0 | 21 |
| 20 | — | 13,5 % | 4,3 s | 7,5 s | 9,0 s | 22 | 0 | 0 | **0** (3 avant la correction 4) | 42 |

- **Erreurs d'interface du script** : le clic de Playwright tombait sur une partie fixe du planning (en-tête des jours, colonne des totaux) qui recouvrait la carte après défilement. C'est un vrai défaut d'accessibilité (focus masqué, WCAG 2.4.11), **corrigé** (marges de défilement de la grille, test navigateur dédié). Les passages ci-dessus ont été mesurés avant cette correction : ces opérations ne sont pas comptées dans les pourcentages, qui portent sur les attributions réellement confirmées ou refusées à l'écran.
- **Génération sur le même mois, pendant les modifications de 10 managers** : 80 opérations, aucune modification écrasée. La génération n'a rien enregistré et en a donné la raison (« le planning a été modifié pendant le calcul… relancez le calcul »).
- **Cohérence, vérifiée par le journal d'audit du serveur** sur toute la série : 3 303 changements sur 172 shifts, 0 rupture de chaîne, 0 titulaire final incohérent, 0 doublon de titulaire, compteurs d'heures exacts pour chaque collaborateur, 0 notification en double.

### Côté serveur seul (sans navigateur, même trafic par écran), deux répétitions

| Sessions | Réaffectations < 2 s | Médiane | 95e centile | Relecture ciblée (médiane / 95e centile) | Délais dépassés | Erreurs |
|---|---|---|---|---|---|---|
| 10 | 100 % / 100 % | 38 / 40 ms | 177 / 158 ms | 57–87 / 325–336 ms | 0 | 0 |
| 20 | 100 % / 100 % | 41 / 42 ms | 275 / 325 ms | 82–92 / 531–560 ms | 0 | 0 |
| 40 | 100 % / 100 % | 91 / 98 ms | 626 / 554 ms | 168–179 / 865–1 129 ms | 0 | 0 |

Avant la correction 4 (interblocage), le même essai à 40 sessions donnait 436 délais dépassés et 373 erreurs « QueuePool limit reached ».

### Évolution à 10 managers, à l'écran, au fil des corrections

| Configuration | < 2 s | Médiane |
|---|---|---|
| Départ : 1 processus, relecture complète à chaque annonce | phase interrompue (lectures jusqu'à 30 s) | — |
| + 4 processus, annonces regroupées | 55 % | 1,9 s |
| + cache des lectures | 35 % | 2,3 s |
| + rafraîchissement ciblé, conflits partagés | 60 % | 1,9 s |
| + 8 processus (essai, non retenu) | 62,5 % | 1,26 s |
| + limite de requêtes simultanées (interblocage corrigé) | 100 % | 639 ms |
| + relectures ciblées après ses propres modifications (final) | 83,8 % / 98,4 % / 100 % | 1,14 s / 346 ms / 201 ms |

## Conclusion

- **Objectif à 10 managers (95 % sous 2 s)** : atteint dans 3 passages sur 4 après la correction de l'interblocage (100 %, 98,4 %, 100 %). Un passage reste en dessous (83,8 %), sur une machine de test chargée à plus de 11 pour 10 cœurs. Dans cet environnement, l'objectif est donc atteint mais **pas garanti**.
- **Goulot principal**, identifié et corrigé : l'interblocage entre les connexions à la base et les threads de l'API. Il expliquait les écrans qui ne chargeaient pas à 20 managers et les délais de 30 s ; il n'y a plus aucun délai dépassé, même à 40 sessions.
- **Serveur seul** : 40 sessions simultanées restent à 100 % sous 2 s (95e centile inférieur à 0,7 s). Le serveur, la base et le code ne sont donc pas le facteur limitant à 10 ou 20 managers.
- **À 20 managers à l'écran** : 13,5 % sous 2 s, mais aucun écran non chargé, aucune erreur serveur, aucun délai dépassé. Deux limites se cumulent pendant ces mesures :
  - la machine de test est saturée (charge de 11 à 14 pour 10 cœurs, navigateurs jusqu'à 4 cœurs) ;
  - les 4 processus de l'API sont à environ 400 %, car les vrais écrans génèrent plus de trafic que le générateur sans navigateur (chargement initial, notifications, flux temps réel).
- **Mesures nécessaires pour 20 managers et plus** (décision D1) :
  - un serveur dédié, et un générateur de charge sur une autre machine ;
  - plusieurs instances de l'API selon le nombre de cœurs (le nombre de processus se règle avec `API_WORKERS`) ;
  - HTTP/2 derrière un proxy TLS, pour supprimer la limite de 6 connexions par navigateur ;
  - ensuite, si nécessaire, un calcul incrémental des conflits (aujourd'hui recalculés sur tout le mois, une fois par révision).

## Limites

- **Une seule machine** fait tourner les navigateurs de test, Docker, l'API, la base et le générateur. À 20 managers, la machine est saturée (charge de 11 à 12 pour 10 cœurs), et les navigateurs occupent à eux seuls jusqu'à 4 cœurs. Une partie du temps mesuré à l'écran vient donc du poste de test lui-même, et non du produit.
- Les résultats varient d'un passage à l'autre : chaque configuration importante a été répétée, et les écarts sont indiqués.
- La production (hébergement, nombre d'instances, HTTP/2, base séparée) reste à choisir (décision D1). Les mesures doivent être refaites sur cet environnement, avec un générateur de charge sur une machine distincte.
