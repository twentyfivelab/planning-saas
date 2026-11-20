# État des lieux et plan — plateforme destinée à une grande entreprise (20/11/2026)

Base : code de la branche `feature/wfm-regles-plafond-identite-rose`, suites de tests (moteur, API, navigateur, unitaires), site local.
La plateforme n'est pas présentée comme commercialisable : règles juridiques non validées (voir § 6).

## 1. État des lieux

**Points solides (vérifiés par des tests)**
- Moteur CP-SAT hiérarchique (couverture → engagements → optimisation), vérificateur indépendant du résultat avant et après enregistrement, plafond mensuel, jours min/max, repos, habilitations par marque, verrous, équité des heures (cible commune d'heures plafonnée par ce que chacun peut réellement atteindre, y compris en tenant compte des collègues qui partagent les mêmes shifts, et objectif contractuel explicite ; sans priorité automatique).
- Multi-entreprise isolé en base (RLS), rôles et périmètre par marque, journal d'audit et historique lisible.
- Parcours complets : assistant de création de mois, budgets préremplis, génération, modifications manuelles contrôlées (dérogations tracées), propositions de remplacement acceptées par les collaborateurs, suivi de couverture, versions, validation et publication, suppression protégée et récupération d'archive, notifications internes.
- Protections de fiabilité : enregistrement automatique avec état réel et « Réessayer », pas d'écriture dans un planning supprimé, annulation fiable d'un calcul, aucune double affectation (verrous et index uniques), propositions protégées contre les doubles clics.

**Défauts bloquants corrigés le 19/11**
- Modifications simultanées : déplacement, horaires, échange, retrait et transfert groupé pouvaient écraser silencieusement la modification d'un autre manager → corrigé (lot 1 ci-dessous).
- Annulation pendant un calcul (solution enregistrée malgré tout) et calcul terminé après la suppression du planning (écriture dans le planning supprimé) → corrigés, protégés en base.

**Difficultés d'utilisation relevées**
- Le résultat d'une génération mélange plusieurs informations (validité, couverture, budgets, équité, optimisation) : à structurer en blocs lisibles (lot 2).
- Beaucoup d'informations techniques (poids, niveaux) : un nouveau manager doit pouvoir s'en passer (lot 4).
- Planning dense avec de nombreux collaborateurs et marques : lisibilité, filtres et en-têtes à revoir (lot 5).

**Limites techniques connues**
- API en un seul processus : sous forte charge, les lectures lourdes simultanées se ralentissent (mesuré, voir `docs/suivi-wfm.md`) ; validation à plusieurs managers à faire (lot 3).
- Temps du moteur : grands mois non prouvés optimaux en 30 s (solution valide, optimisation non terminée) ; au-delà de 150 collaborateurs non mesuré.
- Pas de connexion d'entreprise (SSO) ni d'authentification renforcée ; interface en français seulement.
- Données de démonstration issues de vraies données : une démonstration doit utiliser des données entièrement fictives (lot 6).

## 2. Lots, par ordre d'importance

| Lot | Objet | Bénéfice | État |
|---|---|---|---|
| 0 | Équité mensuelle : cible commune d'heures | Mêmes heures pour tous dans la limite de ce que chacun peut réellement faire | **Terminé le 20/11** (comparaison sur toute l'équipe à volume identique dans `docs/suivi-wfm.md` ; arbitrage renfort / équité : décision D7) |
| 1 | Modifications simultanées et doubles envois | Jamais d'écrasement silencieux ni de double traitement | **Terminé le 19/11** |
| 2 | Résultat de génération explicable (6 blocs) et ordre des priorités du moteur | Un manager comprend en un coup d'œil ce qui est valide, couvert, équilibré, prouvé | **Terminé le 19/11** |
| 3 | Performances à 5, 10, 20 managers + temps de génération selon la taille | Capacités chiffrées, objectif 95 % des attributions < 2 s à 10 managers | À faire |
| 4 | Parcours essentiels simplifiés (créer, budgets, disponibilités, générer, comprendre, modifier, remplacer, historique, publier) | Prise en main sans connaître le moteur | À faire |
| 5 | Qualité visuelle et accessibilité (planning dense, clavier, couleur non seule porteuse d'information, tablette, « Mon espace ») | Présentation professionnelle | À faire |
| 6 | Données de démonstration fictives et parcours de présentation | Démonstration sans données personnelles | À faire |
| 7 | Exigences entreprise : préparation, sauvegarde/restauration vérifiée, compteurs et exports cohérents | Dossier pour une multinationale | À faire |
| 8 | Tuteur et binôme (chevauchement ≠ couverture complète) | Accompagnement des nouveaux | Prévu après les lots 2 à 7 |

## 3. Lot 1 — modifications simultanées (terminé)

- Toutes les modifications d'un shift (déplacement, glisser-déposer, horaires, échange, retrait, transfert groupé, attribution manuelle) transmettent ce que l'écran affichait ; le serveur verrouille le shift et refuse avec « Ce shift vient d'être modifié par quelqu'un d'autre… Rien n'a été modifié. » si la situation a changé ; l'écran se met à jour.
- Double clic ou nouvel envoi après une coupure : la même opération déjà faite est confirmée sans être refaite (aucune double trace, aucune double affectation).
- Shift déjà retiré par un autre : « déjà retiré ou remplacé par quelqu'un d'autre », jamais une erreur technique.
- Tests : API (déplacements simultanés sur deux connexions — un seul appliqué ; vue périmée refusée pour horaires, échange, retrait, transfert groupé « tout ou rien » ; doubles envois) et navigateur (réaffectation et horaire refusés sur une vue périmée, message affiché, modification du collègue conservée).

## 3 bis. Lot 2 — résultat de génération explicable (terminé)

Après chaque génération enregistrée (page « Générer » et fin de l'assistant), six blocs distincts, chacun avec son état (conforme, à regarder, problème, information) :
1. **Règles obligatoires** : résultat du contrôle indépendant (nombre d'affectations revérifiées, règles en cause le cas échéant).
2. **Couverture des besoins** : obligatoires couverts / total, non couverts avec la raison et l'accès aux shifts concernés.
3. **Budgets et volume attribué** : par marque (planifié / budget, strict ou souple) ; volume obligatoire et optionnel ; toute baisse des optionnels expliquée ; « aucun budget saisi » dit clairement.
4. **Équité des heures** : cible commune, cible atteignable, maximum possible et heures de chacun ; collaborateurs au maximum de ce qu'ils peuvent faire, en renfort uniquement, sans shift possible, nettement sous leur cible ou à part réduite (shifts partagés avec d'autres).
5. **Shifts à compléter** : obligatoires non couverts et besoins optionnels non attribués, avec accès direct.
6. **État de l'optimisation** : « meilleure solution prouvée » ou « planning valide et utilisable, optimisation non terminée (durée maximale atteinte) » ; détail par niveau.
L'ordre des priorités du moteur est expliqué sous les blocs. Tests : API (six blocs, états, chiffres cohérents avec le planning) et navigateur (blocs affichés après une génération).

## 4. Capacités attendues par une multinationale

| Capacité | État | Détail | Première présentation |
|---|---|---|---|
| Isolation des données entre entreprises | Disponible | RLS PostgreSQL forcée, testée (lecture et écriture croisées refusées) | Oui |
| Droits par rôle | Disponible | Propriétaire, administrateur, manager, planificateur, responsable de marque, collaborateur, auditeur | Oui |
| Droits par marque | Disponible | Responsable de marque limité à ses marques | Oui |
| Droits par agence, équipe ou site | Prévu | Périmètre à étendre (modèle prêt pour un périmètre) | Phase ultérieure |
| Traçabilité des changements | Disponible | Journal d'audit, historique lisible avec auteur, date de modification et date du shift, suppression tracée et protégée | Oui |
| Connexion d'entreprise (SSO SAML/OIDC) | Prévu | Comptes locaux uniquement aujourd'hui ; un compte sans mot de passe local est déjà géré (réauthentification) | Phase ultérieure (service externe : accord requis) |
| Authentification renforcée (MFA) | Prévu | Limitation des tentatives et sessions serveur disponibles | Phase ultérieure |
| Fuseaux horaires, changements d'heure | Disponible | Fuseau par entreprise ; durées calculées en UTC (passage à l'heure d'été / d'hiver testé) | Oui |
| Langues | Partiel | Français ; catalogue de traductions en place, autres langues à fournir | Phase ultérieure |
| Formats de dates | Partiel | Format suisse (fr-CH) ; à paramétrer par entreprise | Phase ultérieure |
| Exports | Disponible | PDF, Excel, CSV, ICS | Oui |
| Intégration RH et paie | Partiel | Import des collaborateurs (CSV/Excel) ; connecteurs RH/paie prévus | Phase ultérieure |
| Pauses payées ou non dans les compteurs | Partiel | La pause est enregistrée (payée ou non) mais les compteurs ne distinguent pas encore les pauses payées (lot 7) | À clarifier avant la présentation |
| Sauvegarde et restauration | Disponible | Sauvegarde vérifiée à la création ; restauration sur base isolée par script ; à refaire et chronométrer (lot 7) | Oui |

## 5. Ordre des priorités du moteur (résumé, détaillé au lot 2)

1. Règles obligatoires (jamais sacrifiées) : disponibilités, habilitations, repos, jours consécutifs et maximum, plafond mensuel, budgets stricts, verrous. Contrôle indépendant du résultat avant et après enregistrement.
2. Couverture des besoins obligatoires, puis des budgets (volume visé des besoins optionnels).
3. Engagements : objectifs contractuels, quotas de dimanches, budgets souples.
4. Optimisation : équité des heures (cible commune atteignable), préférences, priorité par marque (prioritaire, secondaire, renfort en dernier recours), équilibre des dimanches et des jours, stabilité.

Distinctions : habilitation (marque autorisée ou non : stricte) ; niveau sur la marque (prioritaire, secondaire, renfort : préférence d'emploi, jamais une interdiction) ; restriction obligatoire (indisponibilité, sites, horaires imposés : stricte) ; préférence (horaires préférés : souple) ; disponibilité réelle (jours non bloqués ce mois). L'ancienneté et le mérite n'interviennent jamais automatiquement.

## 6. Règles juridiques

Les règles réglementaires (repos, durées, dimanches…) sont des références initiales marquées « à valider par un spécialiste du droit suisse » ; aucune n'est présentée comme validée. Elles ne seront modifiées qu'après cette validation (décision D4).
