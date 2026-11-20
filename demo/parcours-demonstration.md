# Parcours de démonstration (5 minutes) — données entièrement fictives

**Préparation (une fois)** :

```
.venv/bin/python scripts/ops/demo_seed.py
```

- Le script crée l'entreprise fictive « Horizon Retail SA (démonstration) » : 3 sites, 5 marques, 25 collaborateurs, des budgets.
- Novembre 2026 est publié, décembre 2026 généré en brouillon, et une proposition de remplacement attend une réponse.
- Les accès sont écrits dans `demo/acces-demonstration.local.txt` (fichier local, jamais versionné).
- Aucune autre entreprise n'est touchée.

Ouvrir http://localhost:3000 et se connecter avec `manager@horizon-demo.example`.

| Temps | Écran | Ce que l'on montre | Bénéfice à dire |
|---|---|---|---|
| 0:00 | Tableau de bord | Mois en cours publié, décembre en préparation, alertes et notifications | « Tout ce qui demande une action est visible au même endroit. » |
| 0:30 | Planning → décembre 2026 | Planning général : noms fixes, défilement du mois, couleurs par marque, filtres par site et marque | « Lisible même avec 25 personnes et 3 sites. » |
| 1:00 | Générer → résultat en six blocs | Règles obligatoires revérifiées, couverture, budgets et volume, **équité des heures** (cible commune, tableau par collaborateur), shifts à compléter, état de l'optimisation | « Le calcul est explicable : chaque chiffre a sa raison. Personne n'est favorisé par l'ancienneté ou le mérite. » |
| 1:45 | Planning → clic sur un shift → « Réaffecter à » | Contrôles immédiats ; confirmation ; refus clair si un collègue vient de modifier le même shift | « Jamais d'écrasement silencieux entre managers. » |
| 2:15 | Fiche de Nina Bauer → Relations | Tutrice « pendant toute la plage de son shift » (couverture complète), distincte du simple chevauchement | « Une nouvelle recrue n'est jamais seule, même une heure. » |
| 2:45 | Planning → proposition de remplacement | Remplaçants classés et expliqués ; proposition envoyée ; titulaire conservé jusqu'à l'acceptation | « Le collaborateur répond lui-même ; le planning ne change qu'après acceptation validée. » |
| 3:15 | Se connecter en `lea.marchand@…` → Mon espace | Planning publié, proposition à accepter ou refuser, notifications | « Le collaborateur a son espace, sur téléphone aussi. » |
| 3:45 | Planning → Exports | Excel et PDF : heures effectives et **heures payées** (pauses payées de l'aéroport) | « Les compteurs et la paie partent des mêmes chiffres. » |
| 4:15 | Historique | Qui a fait quoi, quand, sur quel shift ; suppression protégée et récupérable | « Traçabilité complète, utile en cas de contestation. » |
| 4:40 | Nouveau planning → janvier 2027 | Assistant : budgets préremplis, informations manquantes expliquées, génération | « Un nouveau mois est prêt en quelques minutes. » |

**À ne pas montrer comme acquis** :
- les règles légales, qui sont des références initiales à faire valider par un spécialiste du droit suisse ;
- la connexion d'entreprise (SSO) et l'authentification renforcée, prévues ;
- l'envoi d'e-mails, prévu et dépendant d'un choix de service ;
- l'hébergement de production, à décider.
