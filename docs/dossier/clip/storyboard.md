# Storyboard — Clip Chrono (`Workshop2026-M2-G1-VidChrono.mp4`)

> **Contrainte sujet §7 :** ≤ 60 s, **séquence continue sans coupe**. Le clip est une **prise unique**
> d'écran de la démo réelle (dashboard ZTR + terminal `verify_tx`), pendant que l'attaque part du PC
> Attaquant. On n'ajoute aucune coupe : seules les **incrustations** (bandeau de légende) changent aux
> temps ci-dessous. Source de vérité machine : [`storyboard.json`](storyboard.json) — le même budget et
> les mêmes légendes alimentent [`build_clip.sh`](build_clip.sh) et le test
> `scripts/tests/test_clip_chrono.py`.

Les 5 temps correspondent 1:1 à `scripts/demo.sh` (jouable d'une commande) et au récit du dossier (§2).

| # | Temps | De → à | Durée | À l'écran | Preuve affichée |
|---|---|---|---|---|---|
| 1 | **AVANT** | 00:00 → 00:08 | 8 s | État *Nominal* ; terminal joue `scripts/verify_tx` → `exit 0` | score bas, aucun incident |
| 2 | **ATTAQUE** | 00:08 → 00:16 | 8 s | `attacks/run.sh service_flood` depuis le PC Attaquant | `resilience_anomaly_score` qui monte |
| 3 | **DÉTECTION** | 00:16 → 00:28 | 12 s | Le score franchit le seuil → `AnomalyEvent` → incident ouvert sur la timeline | MTTD affiché |
| 4 | **REMÉDIATION** | 00:28 → 00:48 | 20 s | Table de décision appliquée (blocage IP + reload WAF, redémarrage via proxy) ; `verify_tx` rejoué | timeline des actions, **aucune main humaine** |
| 5 | **APRÈS** | 00:48 → 00:58 | 10 s | `verify_tx` → `exit 0` ; incident clos | MTTD/MTTR affichés |

**Budget : 58 s** (marge de 2 s sous la borne de 60 s).

## Plan de cadrage

- **Fond :** dashboard ZTR en plein écran (`dashboard/`) — timeline, `resilience_anomaly_score`, cartes MTTD/MTTR.
- **Incrustation bas-droite :** un terminal qui joue `scripts/demo.sh service_flood` (les `verify_tx` AVANT/APRÈS y sont visibles).
- **Bandeau bas :** la légende du temps courant (incrustée par `build_clip.sh`, pas filmée).
- **Aucune voix, aucun son** (le jury lit le bandeau ; le dossier et les slides portent le discours).

## Message clé (ce que le jury doit voir en 60 s)

Une transaction fictive passe → une attaque réelle la casse → le **modèle ML** détecte → le moteur
**corrige tout seul** → une nouvelle transaction prouve le retour à la normale, **sans aucune intervention
humaine**, MTTD/MTTR à l'appui.
