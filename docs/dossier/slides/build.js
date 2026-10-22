// Génère Workshop2026-M2-G1-Pres.pptx (sujet §7.2) : support d'un oral de 10 minutes, centré sur la présentation
// de l'équipe (une seule slide : les 6 membres et leurs 3 réalisations) avec deux schémas (architecture, démo en 5 temps).
// Direction artistique : nuit profonde, code couleur de l'incident (menthe = sain/rétabli, corail = attaque,
// ambre = détection, bleu = infrastructure), ligne de pouls en motif, animations sobres (fondus uniquement, un bloc à la fois).
// Pipeline : pptxgenjs -> applyTheme (couleurs du thème) -> animate (transitions + animations d'entrée).
// Usage : cd docs/dossier/slides && npm install && node build.js   (sortie : racine du dépôt)
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("./apply_theme");
const { animate } = require("./animate");
const A = require("./assets");

const OUT = path.resolve(__dirname, "../../../Workshop2026-M2-G1-Pres.pptx");

// L'équipe, dans l'ordre de passage. Chaque membre : 3 réalisations (icône Lucide, couleur, titre, détail).
const TEAM = [
  {
    name: "Yanis Capelle", initials: "YC", role: "DÉVELOPPEUR", tone: "mint",
    tagline: "La plateforme, le moteur de reprise, et le fil qui relie tout.",
    items: [
      ["LuServer", "blue", "Plateforme bancaire", "payment-api, auth et front : comptes, virements, cartes, relevés"],
      ["LuWrench", "mint", "Moteur de remédiation", "table de décision, privilèges bornés, contrats d'interfaces"],
      ["LuFileCheck", "amber", "Intégration et gouvernance", "revues et fusions, EBIOS RM, PCA/PRA, NIS2/DORA, dossier"],
    ],
  },
  {
    name: "Louis Nectoux", initials: "LN", role: "DÉVELOPPEUR", tone: "coral",
    tagline: "Celui qui attaque la plateforme, et celui qui la verrouille.",
    items: [
      ["LuSkull", "coral", "Red Team bornée", "scénarios d'attaque, console et runbook du PC Attaquant, chaos"],
      ["LuScanFace", "amber", "Back-office facial", "identifiant, visage, mot de passe ; habilitations de bout en bout"],
      ["LuShieldCheck", "mint", "Durcissement et SOC", "audit de sécurité, règles SOC, tests de bout en bout"],
    ],
  },
  {
    name: "Valentin Furcy", initials: "VF", role: "DÉVELOPPEUR IA", tone: "amber",
    tagline: "Faire voir l'attaque au modèle, en quelques secondes.",
    items: [
      ["LuBrainCircuit", "amber", "Détection sur séries réelles", "captures, calibration : de 37 s à 2 s pour voir un flood"],
      ["LuRadar", "coral", "L'attaquant désigné", "IP source retrouvée dans les journaux du WAF, puis bloquée"],
      ["LuServerCog", "blue", "Une stack qui tient", "lancement fiable, 3 répliques de payment-api, modèle facial"],
    ],
  },
  {
    name: "Aurélien Serre", initials: "AS", role: "DÉVELOPPEUR IA", tone: "blue",
    tagline: "Un assistant qui explique l'incident, sans jamais agir.",
    items: [
      ["LuBot", "blue", "Assistant RAG", "modèle local ≤ 8B, LangChain, Chroma, dans le dashboard"],
      ["LuFileCheck", "mint", "Résumé DSI et post-mortem", "rédigés à partir du journal d'incident"],
      ["LuLock", "amber", "Isolé de l'automate", "réseau séparé ; toute commande proposée exige une confirmation"],
    ],
  },
  {
    name: "Enzo Palermo", initials: "EP", role: "DÉVELOPPEUR", tone: "mint",
    tagline: "Le témoin physique de l'authentification.",
    items: [
      ["LuRadio", "mint", "Firmware ESP8266", "LED bicolore, machine à états, Wi-Fi, HTTP et MQTT"],
      ["LuServerCog", "blue", "Broker MQTT durci", "Mosquitto authentifié, ACL par topic, profil iot"],
      ["LuKeyRound", "amber", "Secrets chiffrés", "SOPS et age : aucun secret en clair dans le dépôt"],
    ],
  },
  {
    name: "Léo Solana", initials: "LS", role: "DÉVELOPPEUR", tone: "amber",
    tagline: "Ce qui fait démarrer la stack, et ce qui entre dans main.",
    items: [
      ["LuFileCog", "amber", "Configuration de l'environnement", "rédaction du .env : les variables dont chaque service a besoin"],
      ["LuTerminal", "mint", "Makefile", "écriture minutieuse des commandes de lancement, de test et de démo"],
      ["LuGitPullRequest", "blue", "Revue des branches", "relecture avant fusion dans main"],
    ],
  },
];

const THEME = {
  name: "Resilience Nuit",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0B1220", lt1: "FFFFFF", dk2: "1A2438", lt2: "E8EDF5",
    accent1: "2EE6A6", accent2: "FF5A5F", accent3: "FFB547", accent4: "5B8CFF", accent5: "8A97AE", accent6: "2A3854",
    hlink: "5B8CFF", folHlink: "8A97AE",
  },
};
const HEX = THEME.colors;
const MONO = "Consolas";

// Système visuel unique, partagé par toutes les slides :
//  - une grille : marge X0, largeur utile CW, en-tête (surtitre + titre) et pied fixes, contenu à partir de TOP ;
//  - une carte : panneau sobre + onglet de couleur en haut à gauche (couleur = rôle dans l'incident) ;
//  - une tuile d'icône, un avatar en anneau (sans halo), une échelle typographique courte ;
//  - la ligne de pouls réservée aux deux slides « héros » (ouverture, clôture), au même endroit.
const X0 = 0.6, CW = 12.133, TOP = 1.6, HX = 0.9;
const MUTED = "A3AEC2";

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13,333 × 7,5 in
  pres.author = "Consortium G1";
  pres.company = "EPSI — Workshop 2026";
  pres.title = "PROJECT RESILIENCE-ALPHA — Zero-Touch Recovery";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  const SH = pres.ShapeType;

  // ---------------------------------------------------------------- visuels
  const BG = { hero: await A.background("hero"), content: await A.background("content") };
  const PULSE = await A.pulse();
  const ICOLORS = { mint: HEX.accent1, coral: HEX.accent2, amber: HEX.accent3, blue: HEX.accent4 };
  const ICON = {};
  const iconNames = new Set(["LuSkull", "LuShieldCheck", "LuServer", "LuDatabase", "LuActivity", "LuBrainCircuit", "LuWrench", "LuCircleCheck"]);
  TEAM.forEach((m) => m.items.forEach(([ic]) => iconNames.add(ic)));
  for (const n of iconNames) for (const [k, hex] of Object.entries(ICOLORS)) ICON[`${n}:${k}`] = await A.icon(n, hex);
  const SCHEME = { mint: C.accent1, coral: C.accent2, amber: C.accent3, blue: C.accent4 };

  // ---------------------------------------------------------------- layouts
  pres.defineSlideMaster({
    title: "CONTENU",
    background: { data: BG.content },
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: X0, y: 0.42, w: 9, h: 0.28, fontFace: MONO, fontSize: 11, color: C.accent1, charSpacing: 3, margin: 0, valign: "bottom" }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: X0, y: 0.74, w: CW, h: 0.62, fontSize: 28, bold: true, color: C.background1, margin: 0, valign: "top", align: "left" }, text: "" } },
      { text: { text: "RESILIENCE-ALPHA   ·   Consortium G1", options: { x: X0, y: 7.0, w: 6, h: 0.26, fontSize: 9, color: C.accent5, margin: 0, charSpacing: 1 } } },
    ],
    slideNumber: { x: X0 + CW - 0.5, y: 7.0, w: 0.5, h: 0.26, fontSize: 9, color: HEX.accent5, align: "right" },
  });
  pres.defineSlideMaster({ title: "HEROS", background: { data: BG.hero }, objects: [] });

  // ---------------------------------------------------------------- outils de composition
  const SPEC = {};
  let s, cur, uid = 0;
  // Une seule règle d'animation, sobre : transition en fondu, et sur les slides qui en ont besoin, un fondu par
  // bloc (une carte entière apparaît d'un coup), en cascade régulière de STEP ms dans le sens de lecture.
  const FADE = 400, STEP = 100;
  const newSlide = (master, section) => {
    s = pres.addSlide({ masterName: master, sectionTitle: section });
    cur = { transition: "fade", groups: [] };
    SPEC[pres.slides.length] = cur;
    return s;
  };
  const group = (trigger) => {
    const g = { trigger, items: [] };
    cur.groups.push(g);
    return (names, rank = 0) =>
      [names].flat(Infinity).forEach((name) => g.items.push({ name, effect: "fade", delay: rank * STEP, dur: FADE }));
  };
  const nm = (label) => `${label} ${++uid}`;
  const T = (text, o) => {
    const name = o.name || nm("texte");
    s.addText(text, { isTextBox: true, margin: 0, color: C.background1, fontSize: 14, valign: "top", ...o, objectName: name });
    return name;
  };
  // Carte : panneau sobre + onglet de couleur en haut à gauche. Renvoie [panneau, onglet].
  const card = (x, y, w, h, tone, o = {}) => {
    const name = nm("carte");
    s.addShape(SH.roundRect, {
      x, y, w, h, rectRadius: 0.08,
      fill: { color: C.text2 },
      line: { color: o.line || C.accent6, width: o.lineWidth ?? 0.75 },
      objectName: name,
    });
    if (!tone) return [name];
    const tab = nm("onglet");
    s.addShape(SH.rect, { x: x + 0.22, y, w: 0.55, h: 0.05, fill: { color: SCHEME[tone] }, line: { type: "none" }, objectName: tab });
    return [name, tab];
  };
  // Tuile d'icône : carré arrondi teinté + icône.
  const tile = (x, y, d, iconName, tone) => {
    const c = nm("tuile");
    s.addShape(SH.roundRect, { x, y, w: d, h: d, rectRadius: 0.08, fill: { color: SCHEME[tone], transparency: 85 }, line: { type: "none" }, objectName: c });
    const i = nm("icône");
    s.addImage({ data: ICON[`${iconName}:${tone}`], x: x + d * 0.22, y: y + d * 0.22, w: d * 0.56, h: d * 0.56, objectName: i });
    return [c, i];
  };
  const icon = (x, y, d, iconName, tone) => {
    const i = nm("icône");
    s.addImage({ data: ICON[`${iconName}:${tone}`], x, y, w: d, h: d, objectName: i });
    return i;
  };
  // Anneau : disque sombre cerclé de couleur + texte (avatar à initiales, numéro d'étape).
  const ring = (x, y, d, tone, text, fontSize, key) => {
    const disc = key ? `!!avatar ${key}` : nm("anneau"), lbl = key ? `!!initiales ${key}` : nm("libellé");
    s.addShape(SH.ellipse, { x, y, w: d, h: d, fill: { color: C.text1 }, line: { color: SCHEME[tone], width: 1.5 }, objectName: disc });
    s.addText(text, { isTextBox: true, x, y, w: d, h: d, margin: 0, align: "center", valign: "middle", fontSize, bold: true, color: SCHEME[tone], objectName: lbl });
    return [disc, lbl];
  };
  const avatar = (x, y, d, m, key, fontSize) => ring(x, y, d, m.tone, m.initials, fontSize, key);
  const rule = (x, y, w) => {
    const name = nm("filet");
    s.addShape(SH.line, { x, y, w, h: 0, line: { color: C.accent6, width: 0.75 }, objectName: name });
    return name;
  };
  const arrow = (x, y, w, h, o = {}) => {
    const name = nm("flèche");
    s.addShape(SH.line, { x, y, w, h, line: { color: o.color || C.accent5, width: o.width || 1.5, endArrowType: o.begin ? undefined : "triangle", beginArrowType: o.begin ? "triangle" : undefined }, objectName: name });
    return name;
  };
  const label = (text, x, y, w, o = {}) =>
    T(text, { x, y, w, h: 0.26, fontFace: MONO, fontSize: 10, color: C.accent5, charSpacing: 2, ...o });
  const pulse = (y, h) => {
    s.addImage({ data: PULSE, x: 0, y, w: 13.333, h, objectName: "!!pouls" });
    return "!!pouls";
  };
  const kickTitle = (kicker, title) => {
    s.addText(kicker, { placeholder: "kicker" });
    s.addText(title, { placeholder: "title" });
  };

  // ================================================================ 1. Titre
  pres.addSection({ title: "Ouverture" });
  newSlide("HEROS", "Ouverture");
  T("Consortium G1", { x: 8.9, y: 0.6, w: 13.333 - HX - 8.9, h: 0.3, fontFace: MONO, fontSize: 11, color: C.accent5, align: "right" });
  T("PROJECT RESILIENCE-ALPHA   ·   WORKSHOP EPSI 2026", { x: HX, y: 1.5, w: 9, h: 0.32, fontFace: MONO, fontSize: 13, color: C.accent1, charSpacing: 4 });
  T([{ text: "Zero-Touch", options: { breakLine: true } }, { text: "Recovery", options: { color: C.accent1 } }],
    { x: HX, y: 1.95, w: 10, h: 2.1, fontSize: 66, bold: true, lineSpacingMultiple: 0.9 });
  T("Une plateforme de paiement qui détecte l'attaque, se répare seule et le prouve par une vraie transaction.",
    { x: HX, y: 4.1, w: 8.5, h: 0.8, fontSize: 20, color: C.background2 });
  pulse(4.95, 1.0);
  T(TEAM.map((m) => m.name).join("   ·   "), { x: HX, y: 6.55, w: 11.5, h: 0.32, fontSize: 12, color: C.accent5 });
  s.addNotes("[0:00 – 0:30] Une phrase : nous avons construit une plateforme de paiement fictive qui, attaquée, se répare seule et prouve son retour à la normale par une vraie transaction. La ligne de pouls est le fil du deck : sain, attaque, détection, reprise.");

  // ================================================================ 2. L'équipe : les 6 membres et leurs 3 réalisations
  pres.addSection({ title: "L'équipe" });
  newSlide("CONTENU", "L'équipe");
  kickTitle("L'ÉQUIPE", "Six développeurs, et ce que chacun a construit");
  const a2 = group("auto");
  const TW = (CW - 2 * 0.2) / 3, TH = 2.6, TTOP = 1.52;
  TEAM.forEach((m, i) => {
    const x = X0 + (i % 3) * (TW + 0.2), y = TTOP + Math.floor(i / 3) * (TH + 0.1);
    a2([
      card(x, y, TW, TH, m.tone),
      avatar(x + 0.22, y + 0.2, 0.46, m, i, 12),
      T(m.name, { x: x + 0.82, y: y + 0.18, w: TW - 1.02, h: 0.28, fontSize: 14, bold: true }),
      T(m.role, { x: x + 0.82, y: y + 0.46, w: TW - 1.02, h: 0.22, fontFace: MONO, fontSize: 9, color: SCHEME[m.tone], charSpacing: 2 }),
      rule(x + 0.22, y + 0.8, TW - 0.44),
      m.items.map(([ic, tone, title, body], k) => {
        const iy = y + 0.92 + k * 0.56;
        return [
          icon(x + 0.22, iy + 0.02, 0.2, ic, tone),
          T(title, { x: x + 0.55, y: iy, w: TW - 0.75, h: 0.22, fontSize: 11, bold: true }),
          T(body, { x: x + 0.55, y: iy + 0.21, w: TW - 0.75, h: 0.3, fontSize: 9, color: MUTED }),
        ];
      }),
    ], i);
  });
  s.addNotes("[0:30 – 6:30] Chacun présente sa carte en une minute, dans l'ordre de la chaîne : " +
    TEAM.map((m) => `${m.name} (« ${m.tagline} »)`).join(" ; ") + ".");

  // ================================================================ 3. Architecture
  pres.addSection({ title: "Le projet" });
  newSlide("CONTENU", "Le projet");
  kickTitle("LE PROJET · ARCHITECTURE", "Une seule porte, une boucle qui se referme");
  const b3 = group("click"), c3 = group("click");
  const NW = (CW - 3 * 0.3) / 4, NH = 1.15, ROW1 = 1.98, ROW2 = 4.42;
  const XS = [0, 1, 2, 3].map((i) => X0 + i * (NW + 0.3));
  const node = (x, y, ic, tone, title, sub, highlight) => [
    ...card(x, y, NW, NH, tone, highlight ? { line: C.accent1, lineWidth: 1.25 } : {}),
    ...tile(x + 0.22, y + 0.33, 0.5, ic, tone),
    T(title, { x: x + 0.9, y: y + 0.26, w: NW - 1.05, h: 0.3, fontSize: 15, bold: true }),
    T(sub, { x: x + 0.9, y: y + 0.58, w: NW - 1.05, h: 0.45, fontSize: 10.5, color: MUTED }),
  ];
  label("CHEMIN MÉTIER", X0, TOP, 4);
  [
    ["LuSkull", "coral", "PC Attaquant", "hotspot du projet, 4 scénarios bornés"],
    ["LuShieldCheck", "mint", "WAF", "ModSecurity + CRS, seul exposé", true],
    ["LuServer", "blue", "Services", "front · auth · payment-api ×3"],
    ["LuDatabase", "blue", "PostgreSQL 16", "réseau data interne"],
  ].forEach(([ic, tone, t, sub, hl], i) => {
    node(XS[i], ROW1, ic, tone, t, sub, hl);
    if (i < 3) arrow(XS[i] + NW + 0.05, ROW1 + NH / 2, 0.2, 0);
  });
  const VY = ROW1 + NH + 0.06, VH = ROW2 - ROW1 - NH - 0.12, LY = VY + VH / 2 - 0.13;
  b3(arrow(XS[3] + NW / 2, VY, 0, VH, { color: C.accent3 }));
  b3(T("métriques · journaux", { x: XS[3] + NW / 2 - 2.45, y: LY, w: 2.3, h: 0.26, fontSize: 11, color: C.accent3, align: "right" }));
  b3(label("BOUCLE DE REPRISE", X0, ROW2 - 0.38, 4));
  [
    [3, "LuActivity", "amber", "Observabilité", "Prometheus · Loki, chaque seconde"],
    [2, "LuBrainCircuit", "amber", "Détection ML", "IsolationForest → AnomalyEvent"],
    [1, "LuWrench", "mint", "Remédiation", "table de décision, jamais exposée"],
    [0, "LuCircleCheck", "mint", "Preuve", "verify_tx + timeline au dashboard"],
  ].forEach(([col, ic, tone, t, sub], i) => {
    b3(node(XS[col], ROW2, ic, tone, t, sub));
    if (col > 0) b3(arrow(XS[col - 1] + NW + 0.05, ROW2 + NH / 2, 0.2, 0, { begin: true }));
  });
  c3(arrow(XS[1] + NW / 2, VY, 0, VH, { color: C.accent1, begin: true }));
  c3(T("bloque l'IP · redémarre · restaure", { x: XS[1] + NW / 2 + 0.15, y: LY, w: 3.2, h: 0.26, fontSize: 11, color: C.accent1 }));
  c3(T("Seuls 80/443 publiés   ·   réseaux data et obs internes   ·   Docker via un proxy : 5 appels autorisés",
    { x: X0, y: 6.25, w: CW, h: 0.3, fontSize: 12, color: C.accent5 }));
  s.addNotes("[6:30 – 8:00] En haut, le chemin métier : un seul composant exposé, le WAF. Clic : la plateforme émet métriques et journaux, le modèle les lit chaque seconde, le moteur décide, la preuve est rejouée. Clic : le moteur agit sur la porte d'entrée et les services — la boucle se referme.");

  // ================================================================ 4. Démo en 5 temps
  newSlide("CONTENU", "Le projet");
  kickTitle("LE PROJET · LA DÉMO", "Cinq temps, une seule commande");
  const a4 = group("auto");
  const SW = (CW - 4 * 0.22) / 5, LINE_Y = 2.3, CARD_Y = 2.9, CARD_H = 2.0;
  const SX = [0, 1, 2, 3, 4].map((i) => X0 + i * (SW + 0.22));
  const frise = nm("frise");
  s.addShape(SH.line, { x: SX[0] + SW / 2, y: LINE_Y, w: SX[4] - SX[0], h: 0, line: { color: C.accent6, width: 1.5 }, objectName: frise });
  [
    ["mint", "Avant", "verify_tx passe : un virement fictif traverse WAF, API et base."],
    ["coral", "Attaque", "service_flood depuis le PC Attaquant, intensité et durée bornées."],
    ["amber", "Détection", "le modèle voit l'anomalie en secondes et désigne l'IP source."],
    ["blue", "Remédiation", "le moteur bloque l'IP, relance si besoin, rejoue verify_tx."],
    ["mint", "Après", "transaction OK : incident clos, MTTD et MTTR affichés."],
  ].forEach(([tone, title, body], i) => {
    const x = SX[i], d = 0.56;
    a4([
      ring(x + SW / 2 - d / 2, LINE_Y - d / 2, d, tone, String(i + 1), 15),
      card(x, CARD_Y, SW, CARD_H, tone),
      T(title, { x: x + 0.22, y: CARD_Y + 0.3, w: SW - 0.44, h: 0.4, fontSize: 18, bold: true, color: SCHEME[tone] }),
      T(body, { x: x + 0.22, y: CARD_Y + 0.82, w: SW - 0.44, h: 1.6, fontSize: 12.5, color: C.background2 }),
    ], i);
  });
  card(X0, 5.35, CW, 0.62);
  T("make demo   ·   aucune main sur le clavier entre ② et ⑤   ·   Clip Chrono ≤ 60 s, sans coupe",
    { x: X0, y: 5.35, w: CW, h: 0.62, fontFace: MONO, fontSize: 12, color: C.accent1, align: "center", valign: "middle" });
  s.addNotes("[8:00 – 9:15] C'est exactement ce que vous verrez en direct. make demo observe et prouve, il n'exécute aucune action corrective. Personne ne touche au clavier côté hôte entre l'attaque et la preuve.");

  // ================================================================ 5. Clôture (miroir de l'ouverture)
  pres.addSection({ title: "Démonstration" });
  newSlide("HEROS", "Démonstration");
  T("À VOUS DE JUGER", { x: HX, y: 1.5, w: 9, h: 0.32, fontFace: MONO, fontSize: 13, color: C.accent1, charSpacing: 4 });
  T("Place à la démo", { x: HX, y: 1.95, w: 11.5, h: 1.1, fontSize: 66, bold: true });
  T("Attaque depuis le PC Attaquant, détection, reprise, preuve — sans toucher au clavier.",
    { x: HX, y: 3.25, w: 11, h: 0.5, fontSize: 20, color: C.background2 });
  pulse(4.95, 1.0);
  TEAM.forEach((m, i) => {
    const x = HX + i * 1.95;
    avatar(x, 6.2, 0.45, m, i, 11);
    T(m.name, { x: x + 0.55, y: 6.2, w: 1.35, h: 0.45, fontSize: 11, bold: true, valign: "middle" });
  });
  s.addNotes("[9:15 – 10:00] Remercier, puis basculer sur la démo live : attaque depuis le PC Attaquant, personne ne touche au clavier côté hôte.");

  // ---------------------------------------------------------------- écriture, thème, animations
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  await animate(OUT, SPEC);
  console.log(`PPTX : ${OUT} (${pres.slides.length} slides)`);
})().catch((e) => { console.error(e); process.exit(1); });
