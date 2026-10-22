# ml/training/data

Données réelles **versionnées** du modèle (fictives : trafic de la plateforme de démo, aucun secret). Le build de l'image
detector les lit s'ils existent ; sinon il retombe sur la baseline synthétique.

| Fichier | Produit par | Contenu |
|---|---|---|
| `baseline_real.csv` | `make capture-baseline` | fenêtres de trafic **normal** (`label=normal`) |
| `attacks_real.csv` | `make capture-attack SC=<scenario>` | fenêtres capturées pendant chaque scénario (`label` = scénario) |
| `calibration.json` | `make calibrate` | seuil calibré, MTTD par scénario, empreinte du modèle |
| `calibration.report.json` | `make calibrate` (toujours, même en échec) | diagnostic : pic par scénario, `separable` par scénario |

Format CSV : `ml/shared/csvio.py` (`ts, 9 features, label, missing`). Procédure complète : `../README.md` §6.
