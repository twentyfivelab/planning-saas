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
- Capacité mesurée sur un portable unique (voir `docs/mesures-managers.md`) : objectif atteint à 10 managers sans être garanti ; 20 managers et plus exigent un serveur dédié et plusieurs instances (décision D1).
- Temps du moteur : grands mois non prouvés optimaux en 30 s (solution valide, optimisation non terminée) ; au-delà de 150 collaborateurs non mesuré.
- Pas de connexion d'entreprise (SSO) ni d'authentification renforcée ; interface en français seulement.
- Démonstration : entreprise entièrement fictive disponible (`scripts/ops/demo_seed.py`) ; ne pas présenter les entreprises issues de données réelles.

## 2. Lots, par ordre d'importance

| Lot | Objet | Bénéfice | État |
|---|---|---|---|
| 0 | Équité mensuelle : cible commune d'heures | Mêmes heures pour tous dans la limite de ce que chacun peut réellement faire | **Terminé le 20/11** (comparaison sur toute l'équipe à volume identique dans `docs/suivi-wfm.md` ; arbitrage renfort / équité : décision D7) |
| 1 | Modifications simultanées et doubles envois | Jamais d'écrasement silencieux ni de double traitement | **Terminé le 19/11** |
| 2 | Résultat de génération explicable (6 blocs) et ordre des priorités du moteur | Un manager comprend en un coup d'œil ce qui est valide, couvert, équilibré, prouvé | **Terminé le 19/11** |
| 3 | Performances à 5, 10, 20 managers | Capacités chiffrées, objectif 95 % des attributions < 2 s à 10 managers | **Terminé le 20/11** : 5 défauts trouvés et corrigés (dont un interblocage et un écrasement pendant une génération). À 10 managers, 100 %, 98,4 % et 100 % sous 2 s, mais 83,8 % sur un 4e passage : atteint, non garanti sur la machine de test. Côté serveur seul, 40 sessions à 100 % sous 2 s. À 20 managers à l'écran, 13,5 % (machine de test et 4 processus saturés). Voir `docs/mesures-managers.md` |
| 4 | Parcours essentiels simplifiés | Prise en main sans connaître le moteur | **Partiel** : libellés clarifiés (compteur des dimanches, tableau de bord, statut des calculs, bandeau juridique), couleurs des marques propres à chaque entreprise, résultat de génération expliqué ; parcours de démonstration vérifié de bout en bout. Pas de test d'utilisabilité avec de vrais nouveaux managers |
| 5 | Qualité visuelle et accessibilité | Présentation professionnelle | **Terminé pour les écrans essentiels** : audit automatique WCAG 2.1 A/AA (axe) sur 11 écrans sans violation grave ni critique ; focus jamais masqué dans le planning ; nom accessible des cartes = texte visible ; aucun débordement horizontal en largeurs bureau, tablette et téléphone. Audit manuel par un spécialiste non réalisé |
| 6 | Données de démonstration fictives et parcours de présentation | Démonstration sans données personnelles | **Terminé** : `scripts/ops/demo_seed.py` (entreprise entièrement fictive, par l'API), `demo/parcours-demonstration.md` (5 minutes) |
| 7 | Exigences entreprise | Dossier pour une multinationale | **Terminé pour ce qui ne dépend pas d'un choix extérieur** : exercice de reprise chronométré sur environnement jetable (`scripts/ops/restore_drill.sh`) ; pauses payées dans les compteurs et exports ; limites de connexion partagées entre processus. SSO, MFA et hébergement : voir § 4 |
| 8 | Tuteur et binôme (chevauchement ≠ couverture complète) | Accompagnement des nouveaux | **Terminé le 20/11** : trois portées (même jour, simple chevauchement, couverture complète avec relais possible), moteur, vérificateur, contrôles manuels et fiche |

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
| Pauses payées ou non dans les compteurs | Disponible | Réglage par site, figé sur chaque pause ; heures payées = travail effectif + pauses payées, identiques dans le planning, les compteurs et les exports CSV, Excel et PDF | Oui |
| Sauvegarde et restauration | Disponible | Exercice de reprise complet chronométré sur un serveur jetable : sauvegarde, restauration, migrations, API, connexion, données identiques (voir `docs/backup-restore.md`) | Oui |

## 5. Ordre des priorités du moteur (résumé, détaillé au lot 2)

1. Règles obligatoires (jamais sacrifiées) : disponibilités, habilitations, repos, jours consécutifs et maximum, plafond mensuel, budgets stricts, verrous. Contrôle indépendant du résultat avant et après enregistrement.
2. Couverture des besoins obligatoires, puis des budgets (volume visé des besoins optionnels).
3. Engagements : objectifs contractuels, quotas de dimanches, budgets souples.
4. Optimisation : équité des heures (cible commune atteignable), préférences, priorité par marque (prioritaire, secondaire, renfort en dernier recours), équilibre des dimanches et des jours, stabilité.

Distinctions : habilitation (marque autorisée ou non : stricte) ; niveau sur la marque (prioritaire, secondaire, renfort : préférence d'emploi, jamais une interdiction) ; restriction obligatoire (indisponibilité, sites, horaires imposés : stricte) ; préférence (horaires préférés : souple) ; disponibilité réelle (jours non bloqués ce mois). L'ancienneté et le mérite n'interviennent jamais automatiquement.

## 6. Règles juridiques

Les règles réglementaires (repos, durées, dimanches…) sont des références initiales marquées « à valider par un spécialiste du droit suisse » ; aucune n'est présentée comme validée. Elles ne seront modifiées qu'après cette validation (décision D4).
