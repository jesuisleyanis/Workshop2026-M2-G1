# Cadrage — Pilier Cybersécurité & Attaques (branche `feat/cyber-redteam`)

> Référent : Louis. Couvre les exigences **R10** (attaque depuis PC distinct), **R11** (WAF), **R12** (SOC), **R13** (secrets), **R14** (durcissement), et contribue à **R15** (privilèges remédiation).
> Travail **défensif / Blue Team + Red Team pédagogique**, strictement limité au SI du projet (réseau `RESILIENCE-G1`, PC Hôte `192.168.137.1`). Données 100 % fictives.

## 1. Périmètre (ce que je possède)

| Composant | Rôle | État actuel |
|---|---|---|
| `attacks/` | Banc d'essai Red Team : 4 scénarios, `run.sh`, `reset.sh`, validateur, kill-switch | ✅ v1 livrée, à jouer depuis le vrai 2e PC |
| `security/waf/` | WAF Nginx + ModSecurity + OWASP CRS (seul point exposé) + exporter Prometheus | ✅ configs + 5 tests |
| `security/sops/` | Gestion des secrets SOPS + age (clés hors git) | ✅ v1 |
| `security/hardening/` | Durcissement conteneurs (non-root, cap_drop, read_only), `audit.sh` | ✅ v1 |
| `infra/grafana` + `infra/loki` (règles SOC) | Fonction SOC = règles Loki/Grafana ruler | ✅ `soc-rules.yml` (relecture + validation live côté moi) |
| `tests/e2e/` (part attaque) | Rejeu des scénarios de bout en bout | 🟨 squelette, à compléter |

> Frontière avec les autres : je **consomme** la stack de l'Infra (WAF déployé, Prom/Loki/Grafana up) et je **déclenche** la chaîne ML → remédiation. Je ne touche ni au code `ml/*` ni à `remediation/*` (sauf lecture de `remediation/decision_table.yml` pour vérifier le contrat).

## 2. Le contrat qui me lie aux autres (non négociable)

Chaque scénario `attacks/scenarios/<nom>.yml` déclare, et c'est vérifié par `validate_scenarios.py` + tests :
`signal_attendu` (métrique Prometheus / motif Loki) → `incident_type` (énum figée `docs/contracts.md §3`) → `remediation_attendue` (action de `remediation/decision_table.yml`) → `critere_de_reussite` = **`verify_tx` repasse OK sans intervention humaine**.

C'est ce qui garantit qu'une attaque est toujours reliée à une détection ML et à une action. Si je change un signal, je le resynchronise avec l'équipe ML (features) et Remédiation (table de décision) — jamais seul.

### Mapping des 4 scénarios livrés
| Scénario | incident_type | Signal | Remédiation attendue | Nature |
|---|---|---|---|---|
| `service_flood` | service_flood | req/s + 5xx + latence ↑ | waf_block_ip + restart_service | restauration de **disponibilité** |
| `auth_abuse` | auth_abuse | 401 ↑ | waf_block_ip + tighten_rate_limit | disponibilité |
| `web_attack` | web_attack | blocages CRS ↑ | confirm_waf_block + waf_blacklist_ip | disponibilité |
| `data_corruption` | data_corruption | erreurs DB + verify_tx KO | restore_pg_dump | correction de **corruption** (≠ dispo) |

## 3. Conventions (reprises de CLAUDE.md, s'appliquent à moi)

- **Definition of Done** par tâche, dans l'ordre : (1) code conforme aux contrats → (2) tests unitaires verts (+ e2e si la tâche touche la chaîne de démo) → (3) README/CDC du composant à jour → (4) ligne mise à jour dans `ROADMAP.md` avec preuve (commit/test).
- **Commits** : `type(scope): sujet`. Mes scopes : `waf`, `attacks`, `sops`, `hardening`, `soc`, `e2e`. Ex : `test(attacks): rejeu service_flood e2e`, `feat(soc): règle Loki pic 401`.
- **Branche** : `feat/cyber-redteam` (celle-ci). PR vers `main` en fin de tâche cohérente.
- **Tests** : `pytest`, chemin critique. Un test par contrat de scénario, un par règle SOC si testable.
- **Secrets** : jamais en clair, jamais commités. SOPS + age, clé privée hors git. `gitleaks` en pre-commit.
- **Garde-fous attaque** : intensité ≤ 100 req/s, durée ≤ 60 s, arrêt automatique, kill-switch (`run.sh --stop`), `reset.sh` idempotent, journal horodaté dans `attacks/.runlog`. **Toute sortie du périmètre = arrêt immédiat + signalement coach.**
- **Pas de CI** pour l'instant (décision équipe) : tests en local.

## 4. Ce qu'il reste à faire

### Priorité 1 — Faire fonctionner la chaîne en vrai (cœur de l'Axe 1 du jury)
- [ ] **Jouer les 4 scénarios depuis le PC Attaquant physique** sur le hotspot, pas seulement le profil Compose `attack`. Vérifier connectivité `curl -k https://192.168.137.1/...` puis `run.sh`. (R10, risque ROADMAP « attaque pas prête sur 2e PC »)
- [ ] Pour chaque scénario : confirmer que le `signal_attendu` apparaît bien dans Prometheus/Loki, que la remédiation se déclenche, que `verify_tx` repasse OK. Mesurer MTTD/MTTR réels.
- [ ] Valider le **kill-switch** et `reset.sh` en conditions réelles (retour à l'état « avant » propre).

### Priorité 2 — SOC & WAF en conditions réelles
- [ ] Relire et **valider les règles SOC** (`infra/grafana`/`infra/loki` `soc-rules.yml`) une fois la stack up : les alertes se déclenchent-elles sur les bons motifs et partent-elles vers l'Alertmanager → webhook remédiation ?
- [ ] Vérifier que le **WAF est bien le seul point exposé** (80/443) et que ModSecurity/CRS bloque `web_attack` ; contrôler l'exporter Prometheus (métriques de blocage visibles).
- [ ] Confirmer que `blocked_ips.conf` / blacklist WAF est bien pilotable par la remédiation (action `waf_blacklist_ip`).

### Priorité 3 — e2e & chaos (J4)
- [ ] Compléter `tests/e2e/test_demo_flow.py` pour **rejouer chaque scénario** de bout en bout (actuellement skip si stack down).
- [ ] **Chaos engineering** : au moins une panne **non-attaque** (ex. kill d'un conteneur, saturation ressource) pour montrer que la reprise autonome ne dépend pas que des attaques. ⬜ pas commencé.

### Priorité 4 — Durcissement & secrets (relecture finale)
- [ ] Relancer `security/hardening/audit.sh` sur la stack déployée (non-root, cap_drop ALL, read_only, limites CPU/RAM, healthchecks).
- [ ] Vérifier qu'aucun secret n'est en clair (`gitleaks`), que les `*.enc.*` sont bien chiffrés et que la clé age de démo est fournie **hors archive**.

### Transverse
- [ ] Mettre mon nom en **Propriétaire** sur les lignes correspondantes de `ROADMAP.md` + remplir le tableau Équipe du `README.md`.
- [ ] Fournir ma matière pour le **dossier** et le **Clip Chrono** : la séquence d'attaque filmée fait partie des 5 temps de la démo.

## 5. Ordre d'attaque conseillé
1. Monter le PC Attaquant tôt et valider la connectivité au WAF (débloque le risque Axe 1).
2. Un scénario de bout en bout qui marche (viser `service_flood` en premier : le plus visible).
3. Les 3 autres scénarios + mesure MTTD/MTTR.
4. SOC/alertes validées en live.
5. e2e qui rejoue tout + 1 scénario de chaos.
6. Relecture durcissement/secrets + packaging sans secrets.
