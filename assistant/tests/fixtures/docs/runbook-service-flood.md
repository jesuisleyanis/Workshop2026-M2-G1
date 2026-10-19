# Runbook - Saturation de service (service_flood)

## Symptômes
Le débit de requêtes explose, la latence p95 augmente et le ratio d'erreurs 5xx grimpe sur payment-api.

## Procédure automatique
Le moteur de remédiation bloque l'adresse IP source au niveau du WAF puis redémarre le service payment-api.
La reprise est validée par la transaction de vérification verify_tx.

## Escalade
Si verify_tx échoue après trois tentatives, l'opérateur est notifié sur le dashboard.
