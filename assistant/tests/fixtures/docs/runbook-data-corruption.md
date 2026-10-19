# Runbook - Corruption de données (data_corruption)

## Symptômes
Les erreurs de base de données augmentent et la transaction de vérification verify_tx échoue.

## Procédure
La remédiation restaure le dernier dump Postgres via Ansible (pg_restore). Il s'agit de la correction d'une
compromission des données, différente d'une simple restauration de disponibilité.

## Objectifs de continuité
RPO de 15 minutes grâce aux sauvegardes planifiées, RTO de 10 minutes.
