# Paramétrage légal

Les règles sont des enregistrements versionnés (`/constraints`) de type **legal**, **exception**, **internal** ou
**preference**, avec juridiction (pays/canton/secteur/convention), validité (`valid_from/valid_to`), version.
- Références initiales : `rest_hours` = 11, `max_consecutive_days` = 6 (statut « à valider »).
- Une **dérogation** exige un motif et enregistre qui l'a activée (`enabled_by`).
- Pauses, travail de nuit, dimanche, jeunes travailleurs, catégories particulières : **non codés en dur** et
  applicabilité non supposée ; à modéliser avec le juriste via de nouvelles règles.
- Les préférences ne peuvent jamais contourner une contrainte dure.
