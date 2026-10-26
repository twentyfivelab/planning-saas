# Conservation des données et droits RGPD/LPD

- Conservation par tenant : `tenants.retention_months` (24 par défaut, à valider par l'entreprise cliente).
- Sessions : expiration `SESSION_TTL_HOURS` ; purge des sessions expirées à planifier (tâche récurrente à ajouter).
- Journal d'audit : append-only ; durée à fixer avec le DPO/juriste.
- Accès : `GET /data-subject/{employee_id}` (propriétaire) exporte les données d'un collaborateur.
- Effacement : `DELETE /data-subject/{employee_id}` anonymise le collaborateur et supprime contrats, disponibilités,
  absences et préférences ; les agrégats de planning sont conservés pour l'historique.
- Aucune donnée personnelle dans les logs applicatifs ; les erreurs 500 ne renvoient aucun détail.
