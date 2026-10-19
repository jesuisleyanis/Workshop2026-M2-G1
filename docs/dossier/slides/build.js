// Génère Workshop2026-M2-G1-Pres.pptx (livrable §7.2) : pitch court (~5 min, 10 slides) devant le jury.
// Usage : cd docs/dossier/slides && npm install && node build.js   (sortie : racine du dépôt)
// Contenu aligné sur docs/dossier/dossier.md ; les valeurs [M] sont à remplacer par les mesures de recette.
"use strict";
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL_DIR
  ? path.join(process.env.PPTX_SKILL_DIR, "scripts/apply_theme.js")
  : "./apply_theme.js");

const OUT = path.resolve(__dirname, "../../../Workshop2026-M2-G1-Pres.pptx");

// ---------------------------------------------------------------- thème : nuit (SOC) + vert « reprise » + rouge « incident »
const THEME = {
  name: "Resilience G1",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0F1B2D", lt1: "FFFFFF", dk2: "3B4A5E", lt2: "EEF2F7",
    accent1: "13A47B", // reprise / OK
    accent2: "D9482B", // incident / attaque
    accent3: "2F6DB5", // détection / ML
    accent4: "E8B13D", // avertissement
    accent5: "7A8CA3", accent6: "C7D2E0",
    hlink: "2F6DB5", folHlink: "7A8CA3",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = "Consortium G1";
pres.title = "PROJECT RESILIENCE-ALPHA — pitch";
const C = pres.SchemeColor;

// ---------------------------------------------------------------- layouts
const FOOT = { x: 0.5, y: 5.2, w: 6, h: 0.3, fontSize: 9, color: C.accent5, margin: 0 };
pres.defineSlideMaster({
  title: "DARK",
  background: { color: THEME.colors.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.5, w: 8.8, h: 1.2, fontSize: 40, bold: true, color: C.background1, margin: 0 } } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 2.75, w: 8.8, h: 1.7, fontSize: 16, color: C.accent6, margin: 0 } } },
    { text: { text: "Workshop National EPSI 2026 · PROJECT RESILIENCE-ALPHA · Consortium G1", options: { ...FOOT, color: C.accent5 } } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: THEME.colors.lt1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.35, w: 9, h: 0.7, fontSize: 28, bold: true, color: C.text1, margin: 0 } } },
    { text: { text: "PROJECT RESILIENCE-ALPHA · Consortium G1", options: { ...FOOT } } },
  ],
  slideNumber: { x: 9.2, y: 5.2, w: 0.4, h: 0.3, fontSize: 9, color: C.accent5 },
});

// ---------------------------------------------------------------- helpers
const T = (slide, text, o) => slide.addText(text, { isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top", ...o });
function card(slide, x, y, w, h, title, body, accent, opts = {}) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `card ${title}` });
  slide.addShape(pres.ShapeType.ellipse, { x: x + 0.18, y: y + 0.18, w: 0.3, h: 0.3, fill: { color: accent }, line: { color: accent }, objectName: `dot ${title}` });
  T(slide, title, { x: x + 0.6, y: y + 0.15, w: w - 0.75, h: 0.4, fontSize: opts.titleSize || 15, bold: true });
  T(slide, body, { x: x + 0.18, y: y + 0.62, w: w - 0.36, h: h - 0.75, fontSize: opts.bodySize || 12, color: C.text2 });
}
function stat(slide, x, y, w, big, label, color) {
  T(slide, big, { x, y, w, h: 0.9, fontSize: 44, bold: true, color, align: "center", valign: "middle" });
  T(slide, label, { x, y: y + 0.95, w, h: 0.8, fontSize: 12, color: C.text2, align: "center" });
}
function box(slide, x, y, w, h, text, fill, color = C.background1, size = 11) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { color: fill }, objectName: `box ${text}` });
  T(slide, text, { x: x + 0.05, y, w: w - 0.1, h, fontSize: size, bold: true, color, align: "center", valign: "middle" });
}
function arrow(slide, x1, y1, x2, y2, color = C.accent5) {
  slide.addShape(pres.ShapeType.line, { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width: 1.5, endArrowType: "triangle" }, objectName: "arrow" });
}

// ================================================================ 1. Titre
pres.addSection({ title: "Ouverture" });
let s = pres.addSlide({ masterName: "DARK", sectionTitle: "Ouverture" });
T(s, "DÉMONSTRATEUR DE CYBER-RÉSILIENCE · ZERO-TOUCH RECOVERY", { x: 0.6, y: 0.9, w: 8.8, h: 0.4, fontSize: 12, color: C.accent1, charSpacing: 2 });
s.addText("PROJECT RESILIENCE-ALPHA", { placeholder: "title" });
s.addText([
  { text: "Une plateforme de paiement fictive encaisse une attaque, détecte l'anomalie par ML, se répare seule et le prouve par une transaction.", options: { breakLine: true } },
  { text: "Consortium G1 — pitch de 5 minutes, puis démonstration en direct.", options: { color: C.accent5 } },
], { placeholder: "body" });
s.addNotes("1 min : mission et démarche. Insister : pas de promesse d'infaillibilité, une reprise automatique conçue, observée et vérifiée sur un périmètre maîtrisé.");

// ================================================================ 2. Mission / critère unique
pres.addSection({ title: "Démarche" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Démarche" });
s.addText("Un seul critère de réussite", { placeholder: "title" });
stat(s, 0.5, 1.3, 2.9, "heures", "reprise manuelle aujourd'hui : de minutes à heures, peu reproductible", C.accent2);
stat(s, 3.55, 1.3, 2.9, "≤ 60 s", "cible : attaque → détection → remédiation → nouvelle transaction OK", C.accent1);
stat(s, 6.6, 1.3, 2.9, "0", "intervention humaine dans la boucle de reprise (sanction ND/0)", C.accent3);
s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: 3.25, w: 9, h: 1.7, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: "principes" });
T(s, [
  { text: "Deux principes codés dans le démonstrateur, pas seulement écrits", options: { bold: true, breakLine: true, paraSpaceAfter: 6 } },
  { text: "Un conteneur qui redémarre n'est pas une preuve : la reprise n'est déclarée que quand une transaction fictive traverse toute la chaîne (verify_tx, code 0).", options: { bullet: true, breakLine: true, paraSpaceAfter: 4 } },
  { text: "Restaurer la disponibilité ≠ corriger une corruption : la table de décision refuse de se charger si les deux familles sont mélangées.", options: { bullet: true } },
], { x: 0.75, y: 3.4, w: 8.5, h: 1.45, fontSize: 13, color: C.text1 });
s.addNotes("Les trois chiffres : l'écart entre aujourd'hui et la cible, et la contrainte du jury. Les deux principes différencient le projet : vérification métier et distinction disponibilité/intégrité, tous deux vérifiés par des tests.");

// ================================================================ 3. Architecture
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Démarche" });
s.addText("Architecture : une seule porte exposée", { placeholder: "title" });
// Colonne gauche : chemin métier
box(s, 0.5, 1.3, 1.5, 0.55, "PC Attaquant", C.accent2);
arrow(s, 2.0, 1.575, 2.55, 1.575, C.accent2);
box(s, 2.55, 1.3, 1.9, 0.55, "WAF · ModSecurity + CRS\n[edge — seul exposé]", C.text1, C.background1, 10);
arrow(s, 3.5, 1.85, 3.5, 2.2);
box(s, 2.3, 2.2, 0.75, 0.5, "front", C.accent5);
box(s, 3.1, 2.2, 1.0, 0.5, "payment-api", C.accent5);
box(s, 4.15, 2.2, 0.75, 0.5, "auth", C.accent5);
arrow(s, 3.6, 2.7, 3.6, 3.05);
box(s, 2.7, 3.05, 1.8, 0.5, "PostgreSQL [data interne]", C.text2, C.background1, 10);
// Colonne droite : chaîne de reprise
box(s, 5.6, 1.3, 1.85, 0.55, "Prometheus · Loki · Grafana\n[obs]", C.accent5, C.background1, 10);
arrow(s, 6.525, 1.85, 6.525, 2.2, C.accent3);
box(s, 5.6, 2.2, 1.85, 0.55, "collector → detector\nIsolationForest (ML)", C.accent3, C.background1, 10);
arrow(s, 6.525, 2.75, 6.525, 3.05, C.accent3);
box(s, 5.6, 3.05, 1.85, 0.55, "Moteur de remédiation\n[app, jamais exposé]", C.accent1, C.background1, 10);
arrow(s, 7.45, 3.325, 7.9, 3.325, C.accent1);
box(s, 7.9, 3.05, 1.6, 0.55, "docker-socket-proxy\n· Ansible · verify_tx", C.accent1, C.background1, 9);
arrow(s, 6.525, 3.6, 6.525, 3.95, C.accent1);
box(s, 5.6, 3.95, 1.85, 0.5, "Dashboard (SSE, MTTD/MTTR)", C.text1, C.background1, 10);
arrow(s, 5.6, 3.325, 4.5, 3.325, C.accent1); // moteur -> plateforme (actions)
T(s, "actions : blocage IP, redémarrage, restauration", { x: 4.35, y: 3.6, w: 1.6, h: 0.5, fontSize: 9, color: C.text2, align: "center" });
T(s, [
  { text: "4 réseaux Compose (edge / app / data interne / obs) ; audit.sh échoue si un autre service que le WAF publie un port.", options: { bullet: true, breakLine: true, paraSpaceAfter: 3 } },
  { text: "Contrats d'interfaces figés en J1 (logs JSON, métriques, AnomalyEvent, table de décision) et vérifiés par des tests.", options: { bullet: true, breakLine: true, paraSpaceAfter: 3 } },
  { text: "Assistant RAG (Ollama ≤ 8B) séparé de l'automate ; chemin SOC (Alertmanager) secondaire, authentifié.", options: { bullet: true } },
], { x: 0.5, y: 4.0, w: 4.9, h: 1.1, fontSize: 11, color: C.text2 });
s.addNotes("Lire de gauche à droite : le chemin métier (attaquant, WAF, services, base interne) et la chaîne de reprise (observabilité, ML, moteur, actions, dashboard). Python/FastAPI partout, React/Tailwind pour les fronts.");

// ================================================================ 4. Démo en 5 temps
pres.addSection({ title: "Démonstration" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Démonstration" });
s.addText("La démo en cinq temps, d'une seule commande", { placeholder: "title" });
const steps = [
  ["1", "Avant", "verify_tx : une transaction fictive traverse WAF → API → base (code 0).", C.accent1],
  ["2", "Attaque", "service_flood depuis le PC Attaquant : rafale bornée (≤ 80 req/s, 30 s), kill-switch.", C.accent2],
  ["3", "Détection", "vecteur de 9 features toutes les 15 s, score IsolationForest > seuil → AnomalyEvent.", C.accent3],
  ["4", "Remédiation", "table de décision : blocage IP (WAF) → redémarrage payment-api via le proxy ; verify_tx après chaque action.", C.accent1],
  ["5", "Après", "verify_tx OK → incident clos ; timeline, MTTD et MTTR affichés sur le dashboard.", C.accent1],
];
steps.forEach(([n, title, body, color], i) => {
  const x = 0.5 + i * 1.84;
  s.addShape(pres.ShapeType.ellipse, { x: x + 0.55, y: 1.35, w: 0.6, h: 0.6, fill: { color }, line: { color }, objectName: `step ${n}` });
  T(s, n, { x: x + 0.55, y: 1.35, w: 0.6, h: 0.6, fontSize: 20, bold: true, color: C.background1, align: "center", valign: "middle" });
  if (i < steps.length - 1) arrow(s, x + 1.2, 1.65, x + 1.84 + 0.5, 1.65);
  T(s, title, { x, y: 2.1, w: 1.7, h: 0.4, fontSize: 16, bold: true, align: "center" });
  T(s, body, { x, y: 2.5, w: 1.7, h: 1.3, fontSize: 11, color: C.text2, align: "center" });
});
s.addShape(pres.ShapeType.roundRect, { x: 0.5, y: 3.95, w: 9, h: 1.05, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: "demo note" });
T(s, [
  { text: "make demo", options: { bold: true, color: C.accent1 } },
  { text: " enchaîne les cinq temps et n'exécute aucune action corrective : il observe et prouve. Le même scénario rejoué pour data_corruption montre la réponse d'intégrité (restauration du dump) et non un redémarrage. Clip Chrono ≤ 60 s sans coupe sur cette séquence.", options: {} },
], { x: 0.75, y: 4.1, w: 8.5, h: 0.8, fontSize: 12, color: C.text1 });
s.addNotes("C'est la séquence du Clip Chrono et de la démo live. Annoncer que personne ne touche au clavier entre l'étape 2 et l'étape 5.");

// ================================================================ 5. Détection ML
pres.addSection({ title: "Technique" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Technique" });
s.addText("Détection : un modèle décide, pas des if", { placeholder: "title" });
card(s, 0.5, 1.3, 4.3, 1.8, "Données et modèle", "Prometheus → 9 features / 15 s (req/s, latence p95, 4xx, 5xx, échecs de login, blocages WAF, CPU, RAM, erreurs DB). IsolationForest, 200 arbres ; seuil 0,6296 = quantile 99,9 % de la baseline ; artefact v1.0.0, SHA-256 vérifié au chargement.", C.accent3);
card(s, 0.5, 3.25, 4.3, 1.8, "Limites assumées", "Baseline et attaques synthétiques : avant production, 2–4 semaines de trafic réel et revue du seuil. Le type d'incident est une heuristique de routage : le modèle décide qu'il y a anomalie, la table décide quoi faire. Faux positif = un redémarrage inutile, borné par le cooldown.", C.accent4, { bodySize: 11 });
s.addTable([
  [{ text: "Scénario", options: { bold: true, fill: { color: THEME.colors.lt2 } } }, { text: "Détection (modèle seul)", options: { bold: true, fill: { color: THEME.colors.lt2 } } }],
  ["service_flood", "100 %"], ["auth_abuse", "98,6 %"], ["web_attack", "95,7 %"], ["data_corruption", "100 %"],
  [{ text: "Faux positifs (2 000 fenêtres normales)", options: { bold: true } }, { text: "0", options: { bold: true, color: THEME.colors.accent1 } }],
], { x: 5.1, y: 1.3, w: 4.4, colW: [2.6, 1.8], fontSize: 12, color: THEME.colors.dk1, border: { type: "solid", color: THEME.colors.accent6, pt: 0.75 }, rowH: 0.36, margin: 0.05 });
T(s, "Jeu d'évaluation synthétique (ml/training/artifacts/v1.0.0/baseline_stats.json). 100 % avec le garde-fou statistique (z ≥ 12,97), documenté comme filet, pas comme décideur.", { x: 5.1, y: 3.6, w: 4.4, h: 0.9, fontSize: 11, color: C.text2, italic: true });
s.addNotes("Répondre au §3.3 du sujet : données, préparation (z-score avec plancher), modèle, résultats, limites. Le seuil n'est pas une constante : il est dérivé de la distribution des scores.");

// ================================================================ 6. Remédiation et privilèges
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Technique" });
s.addText("Remédiation autonome, privilèges bornés", { placeholder: "title" });
const hdr = (t) => ({ text: t, options: { bold: true, fill: { color: THEME.colors.lt2 } } });
s.addTable([
  [hdr("incident_type"), hdr("Actions (dans l'ordre)"), hdr("Famille")],
  ["service_flood", "waf_block_ip → restart_service(payment-api)", "Disponibilité"],
  ["auth_abuse", "waf_block_ip → tighten_rate_limit(auth, ×0,5)", "Accès"],
  ["web_attack", "confirm_waf_block (Loki) → waf_blacklist_ip", "Confinement"],
  [{ text: "data_corruption", options: { bold: true } }, { text: "restore_pg_dump(latest) — seul", options: { bold: true } }, { text: "Intégrité", options: { bold: true, color: THEME.colors.accent2 } }],
  ["unknown", "dry_run_report puis escalade", "Aucune action destructive"],
], { x: 0.5, y: 1.3, w: 5.6, colW: [1.45, 2.95, 1.2], fontSize: 11, color: THEME.colors.dk1, border: { type: "solid", color: THEME.colors.accent6, pt: 0.75 }, rowH: 0.34, margin: 0.05 });
T(s, "Chaque action modifiante est suivie de verify_tx (5 essais / 3 s) ; cooldown 60 s, 3 tentatives, puis escalade notify_operator. Idempotence, incident actif dédoublonné, dry_run forçable.", { x: 0.5, y: 3.55, w: 5.6, h: 0.75, fontSize: 11, color: C.text2 });
card(s, 6.4, 1.3, 3.1, 3.7, "Privilèges (point jury)", "• Socket Docker en lecture seule dans un proxy HAProxy : 5 couples méthode/chemin autorisés (ping, list, inspect, restart, HUP), jamais exec/create.\n• Bearer interne (SOPS, fail closed), aucun port publié, jamais sur edge.\n• Playbooks nommés, exécutés dans le conteneur ; listes blanches ; IP de l'hôte jamais bloquée.\n• Non-root, cap_drop ALL, no-new-privileges.\n• Token volé = au pire 3 redémarrages tracés.", C.accent1, { bodySize: 11 });
s.addNotes("La table YAML est la seule source de vérité ; le moteur ne contient que des invariants de sécurité. Expliquer pourquoi le socket brut serait root sur l'hôte et pourquoi les variables des proxys génériques sont trop larges.");

// ================================================================ 7. Sécurité & Red Team
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Technique" });
s.addText("Red Team bornée, défense en profondeur", { placeholder: "title" });
const sc = [
  ["service_flood", "saturation applicative (T1499.002)", C.accent2],
  ["auth_abuse", "credential stuffing (T1110.004)", C.accent2],
  ["web_attack", "SQLi / traversée, bloquées par le CRS (T1190)", C.accent2],
  ["data_corruption", "altération réversible de données fictives (T1565.001)", C.accent4],
];
T(s, "4 scénarios = contrats Red ↔ Blue (signal, incident_type, remédiation attendue, critère)", { x: 0.5, y: 1.25, w: 4.4, h: 0.5, fontSize: 13, bold: true });
sc.forEach(([n, d, color], i) => {
  const y = 1.8 + i * 0.78;
  s.addShape(pres.ShapeType.ellipse, { x: 0.5, y: y + 0.12, w: 0.28, h: 0.28, fill: { color }, line: { color }, objectName: `sc ${n}` });
  T(s, n, { x: 0.95, y, w: 3.9, h: 0.3, fontSize: 13, bold: true });
  T(s, d, { x: 0.95, y: y + 0.3, w: 3.9, h: 0.4, fontSize: 11, color: C.text2 });
});
T(s, "Périmètre strict : cible = la stack du projet sur RESILIENCE-G1, ≤ 100 req/s, ≤ 60 s, arrêt automatique, kill-switch, reset. Pannes non malveillantes (chaos) en complément.", { x: 0.5, y: 4.4, w: 4.4, h: 0.7, fontSize: 10, color: C.text2, italic: true });
card(s, 5.2, 1.25, 4.3, 3.75, "Mesures défensives", "• WAF Nginx + ModSecurity + OWASP CRS, image officielle épinglée, non-root, seul point exposé, deny-list IP rechargeable à chaud.\n• Secrets : SOPS + age, clé privée hors git, gitleaks en pre-commit, archive re-scannée (noms et contenu).\n• Durcissement : non-root, cap_drop ALL, no-new-privileges, read_only, limites CPU/RAM, healthchecks ; Postgres non-root sans capability.\n• Fonction SOC : logs JSON normalisés → Loki ; 4 règles Grafana + miroir Prometheus → Alertmanager → moteur (authentifié).\n• Écarts assumés : pas de MFA, JWT symétrique partagé, TLS auto-signé, sauvegardes sur le même hôte.", C.accent1, { bodySize: 11 });
s.addNotes("Le WAF est la seule porte ; le reste est interne. Dire les écarts avant que le jury ne les trouve.");

// ================================================================ 8. Résultats des essais
pres.addSection({ title: "Résultats" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Résultats" });
s.addText("Résultats : prouvé, et encore à mesurer", { placeholder: "title" });
s.addChart(pres.ChartType.bar, [{
  name: "Tests automatisés verts (19 oct. 2026)",
  labels: ["dashboard", "remediation", "assistant", "payment-api", "ml", "front", "auth", "waf", "attacks", "scripts", "infra", "libs"],
  values: [121, 104, 97, 54, 50, 44, 35, 22, 16, 16, 11, 10],
}], {
  x: 0.5, y: 1.25, w: 5.3, h: 3.8, barDir: "bar", chartColors: [THEME.colors.accent3],
  showTitle: true, title: "Tests automatisés verts par composant (580 au total)", titleFontSize: 12, titleColor: THEME.colors.dk1, titleFontFace: "+mn-lt",
  showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: THEME.colors.dk2, dataLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 10, catAxisLabelColor: THEME.colors.dk2, catAxisLabelFontFace: "+mn-lt", catGridLine: { style: "none" },
  valAxisLabelFontSize: 9, valAxisLabelColor: THEME.colors.accent5, valAxisLabelFontFace: "+mn-lt", valGridLine: { color: THEME.colors.accent6, size: 0.5 },
  valAxisMaxVal: 140, showLegend: false, catAxisOrientation: "maxMin",
});
s.addTable([
  [hdr("Scénario"), hdr("RTO perçu p95"), hdr("Cible")],
  ["service_flood", "[M]", "≤ 60 s"], ["auth_abuse", "[M]", "≤ 60 s"], ["web_attack", "[M]", "immédiat"], ["data_corruption", "[M]", "≤ 2 min"],
], { x: 6.1, y: 1.25, w: 3.4, colW: [1.4, 1.1, 0.9], fontSize: 11, color: THEME.colors.dk1, border: { type: "solid", color: THEME.colors.accent6, pt: 0.75 }, rowH: 0.34, margin: 0.05 });
T(s, "[M] = mesuré en recette J4 (≥ 10 rejeux par scénario). RTO perçu = délai de détection + MTTR. Règle : si la cible n'est pas tenue, on révise la cible, pas la mesure.", { x: 6.1, y: 3.05, w: 3.4, h: 0.95, fontSize: 10, color: C.text2, italic: true });
T(s, "Tests e2e (7) rejouent les 5 temps contre la stack réelle, dont data_corruption KO → OK. Chaque maillon du plan d'exécution est testé isolément (y compris l'exécution réelle du playbook WAF).", { x: 6.1, y: 4.05, w: 3.4, h: 1.0, fontSize: 10, color: C.text2 });
s.addNotes("Honnêteté : les tests prouvent les contrats et la logique ; les MTTR viennent de la recette sur la machine hôte. Remplacer les [M] avant la soutenance.");

// ================================================================ 9. Gouvernance
pres.addSection({ title: "Gouvernance" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Gouvernance" });
s.addText("Gouvernance reliée au démonstrateur", { placeholder: "title" });
card(s, 0.5, 1.25, 2.9, 3.75, "EBIOS RM", "6 scénarios opérationnels = les 4 attaques + secret exposé + abus de l'automate.\n\nRisque initial : 5 Élevés (12). Résiduel : 0 Élevé ; 5 Moyens proposés à l'acceptation de la direction avec un indicateur chacun ; abus de l'automate ramené à Faible (3) par le proxy restreint.\n\nCoût d'arrêt : ~60 €/min direct, mais les coûts réglementaires croissent par seuils de durée — l'automatisation change la classe de l'incident.", C.accent4, { bodySize: 11 });
card(s, 3.55, 1.25, 2.9, 3.75, "PCA / PRA", "Paiement : RTO ≤ 60 s, RPO 0 (redémarrage, pas de restauration).\nDonnées : RTO ≤ 2 min, RPO ≤ 5 min (dump périodique) — perte bornée, à accepter explicitement.\nSinistre majeur : reconstruction manuelle ≤ 60 min, RPO ≤ 1 h — plus zero-touch.\n\nL'humain décide avant (table versionnée, RTO/RPO), l'automate exécute pendant, l'humain analyse après (RACI).", C.accent1, { bodySize: 11 });
card(s, 6.6, 1.25, 2.9, 3.75, "NIS2 / DORA", "DORA = référentiel principal (entité financière) ; NIS2 art. 21 en grille croisée. Aucune conformité revendiquée : démontré / partiel / non démontrable en 4 jours.\n\nArbitrages : reprise hybride (validation humaine avant restauration destructive en production) ; WAL + réplica pour un RPO ~0 ; ré-entraîner sur trafic réel ; Vault + JWT asymétrique ; SIEM avec rétention.\n\nFeuille de route 30 / 90 / 180 jours.", C.accent3, { bodySize: 11 });
s.addNotes("Axe 4 : chaque recommandation s'appuie sur un élément vérifiable du dépôt (invariants, journal, métriques). Insister sur la distinction classe d'incident / coût direct.");

// ================================================================ 10. Limites, contributions, conclusion
pres.addSection({ title: "Conclusion" });
s = pres.addSlide({ masterName: "DARK", sectionTitle: "Conclusion" });
s.addText("En contexte industriel", { placeholder: "title" });
s.addText([
  { text: "Réplication et second site · modèle entraîné sur trafic réel, dérive surveillée · validation humaine avant restauration destructive · expiration des mesures · CI, SIEM, MFA, rotation des secrets.", options: { breakLine: true, paraSpaceAfter: 6 } },
  { text: "Contributions : commits « type(scope) » + ROADMAP.md (propriétaire et preuve par tâche). Dév/Infra/Transformation : Yanis · Cyber : Louis · autres piliers : à compléter.", options: { color: C.accent5 } },
], { placeholder: "body" });
T(s, "Place à la démonstration.", { x: 0.6, y: 4.5, w: 8.8, h: 0.5, fontSize: 20, bold: true, color: C.accent1 });
s.addNotes("Clôturer sur les limites (crédibilité) puis enchaîner sur la démo live : 3 minutes, attaque depuis le PC Attaquant, personne ne touche au clavier côté hôte.");

// ---------------------------------------------------------------- écriture + thème
(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log(`PPTX : ${OUT}`);
})().catch((e) => { console.error(e); process.exit(1); });
