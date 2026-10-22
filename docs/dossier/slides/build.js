// Génère Workshop2026-M2-G1-Pres.pptx (sujet §7.2) : support d'un oral de 10 minutes, centré sur la présentation
// de l'équipe (une slide par membre) avec deux schémas (architecture, démo en 5 temps).
// Direction artistique : nuit profonde, code couleur de l'incident (menthe = sain/rétabli, corail = attaque,
// ambre = détection, bleu = infrastructure), ligne de pouls en motif, transitions Morph et apparitions en cascade.
// Pipeline : pptxgenjs -> applyTheme (couleurs du thème) -> animate (Morph + animations d'entrée).
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
  const ICOLORS = { mint: HEX.accent1, coral: HEX.accent2, amber: HEX.accent3, blue: HEX.accent4, white: "FFFFFF" };
  const ICON = {};
  const iconNames = new Set(["LuSkull", "LuShieldCheck", "LuServer", "LuDatabase", "LuActivity", "LuBrainCircuit", "LuWrench", "LuCircleCheck"]);
  TEAM.forEach((m) => m.items.forEach(([ic]) => iconNames.add(ic)));
  for (const n of iconNames) for (const [k, hex] of Object.entries(ICOLORS)) ICON[`${n}:${k}`] = await A.icon(n, hex);
  const DOT = {};
  for (const [k, hex] of Object.entries(ICOLORS)) DOT[k] = await A.glowDot(hex);
  const SCHEME = { mint: C.accent1, coral: C.accent2, amber: C.accent3, blue: C.accent4, white: C.background1 };

  // ---------------------------------------------------------------- layouts
  pres.defineSlideMaster({
    title: "CONTENU",
    background: { data: BG.content },
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: 0.7, y: 0.5, w: 9, h: 0.32, fontFace: MONO, fontSize: 12, color: C.accent1, charSpacing: 3, margin: 0, valign: "bottom" }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 0.86, w: 11.93, h: 0.8, fontSize: 34, bold: true, color: C.background1, margin: 0, valign: "top", align: "left" }, text: "" } },
      { text: { text: "RESILIENCE-ALPHA   ·   Consortium G1", options: { x: 0.7, y: 6.98, w: 6, h: 0.28, fontSize: 10, color: C.accent5, margin: 0, charSpacing: 1 } } },
    ],
    slideNumber: { x: 12.13, y: 6.98, w: 0.5, h: 0.28, fontSize: 10, color: HEX.accent5, align: "right" },
  });
  pres.defineSlideMaster({ title: "HEROS", background: { data: BG.hero }, objects: [] });

  // ---------------------------------------------------------------- outils de composition
  const SPEC = {};
  let s, cur, uid = 0;
  const newSlide = (master, section, transition = "morph") => {
    s = pres.addSlide({ masterName: master, sectionTitle: section });
    cur = { transition, groups: [] };
    SPEC[pres.slides.length] = cur;
    return s;
  };
  const group = (trigger) => {
    const g = { trigger, items: [] };
    cur.groups.push(g);
    return (names, effect = "fade", delay = 0, dur) => [].concat(names).forEach((name) => g.items.push({ name, effect, delay, dur }));
  };
  const nm = (label) => `${label} ${++uid}`;
  const T = (text, o) => {
    const name = o.name || nm("texte");
    s.addText(text, { isTextBox: true, margin: 0, color: C.background1, fontSize: 14, valign: "top", ...o, objectName: name });
    return name;
  };
  const card = (x, y, w, h, o = {}) => {
    const name = o.name || nm("carte");
    s.addShape(SH.roundRect, {
      x, y, w, h, rectRadius: o.radius ?? 0.12,
      fill: { color: o.fill || C.text2, transparency: o.transparency ?? 12 },
      line: { color: o.line || C.accent6, width: o.lineWidth ?? 1, transparency: o.lineTransparency ?? 0 },
      shadow: { type: "outer", color: "000000", blur: 14, offset: 4, angle: 90, opacity: 0.35 },
      objectName: name,
    });
    return name;
  };
  // Pastille : cercle teinté + icône (le motif d'icône du deck).
  const badge = (x, y, d, iconName, tone) => {
    const c = nm("pastille");
    s.addShape(SH.ellipse, { x, y, w: d, h: d, fill: { color: SCHEME[tone], transparency: 84 }, line: { color: SCHEME[tone], width: 1.25, transparency: 45 }, objectName: c });
    const i = nm("icône");
    s.addImage({ data: ICON[`${iconName}:${tone}`], x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52, objectName: i });
    return [c, i];
  };
  // Avatar : halo lumineux + disque teinté + initiales. `key` stable pour que Morph relie la slide équipe et la slide du membre.
  const avatar = (x, y, d, m, key, fontSize) => {
    const halo = `!!halo ${key}`, disc = `!!avatar ${key}`, ini = `!!initiales ${key}`;
    s.addImage({ data: DOT[m.tone], x: x - d * 0.35, y: y - d * 0.35, w: d * 1.7, h: d * 1.7, transparency: 35, objectName: halo });
    s.addShape(SH.ellipse, { x, y, w: d, h: d, fill: { color: C.text1, transparency: 0 }, line: { color: SCHEME[m.tone], width: 2 }, objectName: disc });
    s.addText(m.initials, { isTextBox: true, x, y, w: d, h: d, margin: 0, align: "center", valign: "middle", fontSize, bold: true, color: SCHEME[m.tone], objectName: ini });
    return [halo, disc, ini];
  };
  const arrow = (x, y, w, h, o = {}) => {
    const name = nm("flèche");
    s.addShape(SH.line, { x, y, w, h, line: { color: o.color || C.accent5, width: o.width || 1.75, endArrowType: o.begin ? undefined : "triangle", beginArrowType: o.begin ? "triangle" : undefined }, objectName: name });
    return name;
  };
  const pulse = (x, y, w, h) => {
    s.addImage({ data: PULSE, x, y, w, h, objectName: "!!pouls" });
    return "!!pouls";
  };
  const kickTitle = (kicker, title) => {
    s.addText(kicker, { placeholder: "kicker" });
    s.addText(title, { placeholder: "title" });
  };

  // ================================================================ 1. Titre
  pres.addSection({ title: "Ouverture" });
  newSlide("HEROS", "Ouverture", "fade");
  const a1 = group("auto");
  a1(T("PROJECT RESILIENCE-ALPHA   ·   WORKSHOP EPSI 2026", { x: 0.9, y: 1.45, w: 9, h: 0.35, fontFace: MONO, fontSize: 14, color: C.accent1, charSpacing: 4 }), "fade");
  a1(T("Consortium G1", { x: 8.9, y: 0.6, w: 3.55, h: 0.3, fontFace: MONO, fontSize: 11, color: C.accent5, align: "right" }), "fade");
  a1(T([{ text: "Zero-Touch", options: { breakLine: true } }, { text: "Recovery", options: { color: C.accent1 } }],
    { x: 0.9, y: 1.95, w: 10, h: 2.2, fontSize: 72, bold: true, lineSpacingMultiple: 0.9 }), "float", 150, 800);
  a1(T("Une plateforme de paiement qui détecte l'attaque, se répare seule et le prouve par une vraie transaction.",
    { x: 0.9, y: 4.2, w: 8.2, h: 0.9, fontSize: 20, color: C.background2 }), "float", 450, 800);
  a1(pulse(0, 5.15, 13.333, 1.1), "wipe", 800, 1600);
  a1(T(TEAM.map((m) => m.name).join("   ·   "), { x: 0.9, y: 6.6, w: 11.5, h: 0.35, fontSize: 13, color: C.accent5 }), "fade", 1600);
  s.addNotes("[0:00 – 0:30] Une phrase : nous avons construit une plateforme de paiement fictive qui, attaquée, se répare seule et prouve son retour à la normale par une vraie transaction. La ligne de pouls est le fil du deck : sain, attaque, détection, reprise.");

  // ================================================================ 2. L'équipe
  pres.addSection({ title: "L'équipe" });
  newSlide("CONTENU", "L'équipe");
  kickTitle("L'ÉQUIPE", "Six développeurs, une plateforme qui se répare seule");
  const a2 = group("auto");
  TEAM.forEach((m, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.7 + col * 4.07, y = 1.95 + row * 2.42, t = i * 170;
    a2(card(x, y, 3.79, 2.15), "float", t);
    a2(avatar(x + 0.4, y + 0.55, 1.05, m, i, 24), "zoom", t + 120, 500);
    a2(T(m.name, { x: x + 1.75, y: y + 0.62, w: 1.95, h: 0.75, fontSize: 19, bold: true }), "fade", t + 200);
    a2(T(m.role, { x: x + 1.75, y: y + 1.38, w: 1.95, h: 0.3, fontFace: MONO, fontSize: 11, color: SCHEME[m.tone], charSpacing: 2 }), "fade", t + 260);
  });
  s.addNotes("[0:30 – 1:15] Nous sommes six, tous développeurs, dont deux orientés IA. Chacun présentera en une minute ce qu'il a construit, dans l'ordre de la chaîne : plateforme, attaque, détection, assistant, objet connecté.");

  // ================================================================ 3. Architecture
  pres.addSection({ title: "Le projet" });
  newSlide("CONTENU", "Le projet");
  kickTitle("LE PROJET · ARCHITECTURE", "Une seule porte, une boucle qui se referme");
  const a3 = group("auto"), b3 = group("click"), c3 = group("click");
  const XS = [0.7, 3.86, 7.02, 10.18], NW = 2.45, NH = 1.3, TOP = 2.2, BOT = 4.62;
  const node = (x, y, ic, tone, title, sub, highlight) => {
    const out = [card(x, y, NW, NH, highlight ? { line: C.accent1, lineWidth: 1.5 } : {})];
    out.push(...badge(x + 0.2, y + 0.33, 0.62, ic, tone));
    out.push(T(title, { x: x + 0.95, y: y + 0.24, w: NW - 1.05, h: 0.38, fontSize: 16, bold: true }));
    out.push(T(sub, { x: x + 0.95, y: y + 0.62, w: NW - 1.05, h: 0.6, fontSize: 11.5, color: C.accent5 }));
    return out;
  };
  a3(T("CHEMIN MÉTIER", { x: 0.7, y: 1.85, w: 4, h: 0.28, fontFace: MONO, fontSize: 11, color: C.accent5, charSpacing: 2 }), "fade");
  [
    ["LuSkull", "coral", "PC Attaquant", "hotspot du projet, 4 scénarios bornés"],
    ["LuShieldCheck", "mint", "WAF", "ModSecurity + CRS, seul exposé", true],
    ["LuServer", "blue", "Services", "front · auth · payment-api ×3"],
    ["LuDatabase", "blue", "PostgreSQL 16", "réseau data interne"],
  ].forEach(([ic, tone, t, sub, hl], i) => {
    a3(node(XS[i], TOP, ic, tone, t, sub, hl), "float", 150 + i * 220);
    if (i < 3) a3(arrow(XS[i] + NW + 0.06, TOP + NH / 2, XS[i + 1] - XS[i] - NW - 0.12, 0), "fade", 300 + i * 220);
  });
  b3(arrow(11.405, TOP + NH + 0.06, 0, BOT - TOP - NH - 0.12, { color: C.accent3 }), "wipe", 0, 500);
  b3(T("métriques · journaux", { x: 8.9, y: 3.83, w: 2.35, h: 0.3, fontSize: 11.5, color: C.accent3, align: "right" }), "fade", 100);
  b3(T("BOUCLE DE REPRISE", { x: 0.7, y: 4.27, w: 4, h: 0.28, fontFace: MONO, fontSize: 11, color: C.accent5, charSpacing: 2 }), "fade", 100);
  [
    [3, "LuActivity", "amber", "Observabilité", "Prometheus · Loki, chaque seconde"],
    [2, "LuBrainCircuit", "amber", "Détection ML", "IsolationForest → AnomalyEvent"],
    [1, "LuWrench", "mint", "Remédiation", "table de décision, jamais exposée"],
    [0, "LuCircleCheck", "mint", "Preuve", "verify_tx + timeline au dashboard"],
  ].forEach(([col, ic, tone, t, sub], i) => {
    b3(node(XS[col], BOT, ic, tone, t, sub), "float", 250 + i * 230);
    if (col > 0) b3(arrow(XS[col - 1] + NW + 0.06, BOT + NH / 2, XS[col] - XS[col - 1] - NW - 0.12, 0, { begin: true }), "fade", 400 + i * 230);
  });
  c3(arrow(XS[1] + NW / 2, TOP + NH + 0.06, 0, BOT - TOP - NH - 0.12, { color: C.accent1, begin: true }), "wipe", 0, 500);
  c3(T("bloque l'IP · redémarre · restaure", { x: XS[1] + NW / 2 + 0.15, y: 3.83, w: 3.2, h: 0.3, fontSize: 11.5, color: C.accent1 }), "fade", 100);
  c3(T("Seuls 80/443 publiés   ·   réseaux data et obs internes   ·   Docker via un proxy : 5 appels autorisés",
    { x: 0.7, y: 6.2, w: 11.93, h: 0.3, fontSize: 12.5, color: C.accent5 }), "fade", 300);
  s.addNotes("[1:15 – 2:30] En haut, le chemin métier : un seul composant exposé, le WAF. Clic : la plateforme émet métriques et journaux, le modèle les lit chaque seconde, le moteur décide, la preuve est rejouée. Clic : le moteur agit sur la porte d'entrée et les services — la boucle se referme.");

  // ================================================================ 4. Démo en 5 temps
  newSlide("CONTENU", "Le projet");
  kickTitle("LE PROJET · LA DÉMO", "Cinq temps, une seule commande");
  const a4 = group("auto");
  const CX = [1.6, 4.13, 6.67, 9.2, 11.73], LINE_Y = 3.0;
  const frise = nm("frise");
  s.addShape(SH.line, { x: 1.6, y: LINE_Y, w: 10.13, h: 0, line: { color: C.accent6, width: 2 }, objectName: frise });
  a4(frise, "wipe", 0, 1400);
  [
    ["mint", "Avant", "verify_tx passe : un virement fictif traverse WAF, API et base."],
    ["coral", "Attaque", "service_flood depuis le PC Attaquant, intensité et durée bornées."],
    ["amber", "Détection", "le modèle voit l'anomalie en secondes et désigne l'IP source."],
    ["blue", "Remédiation", "le moteur bloque l'IP, relance si besoin, rejoue verify_tx."],
    ["mint", "Après", "transaction OK : incident clos, MTTD et MTTR affichés."],
  ].forEach(([tone, title, body], i) => {
    const d = 1.1, cx = CX[i], t = 250 + i * 300;
    const dot = nm("nœud");
    s.addImage({ data: DOT[tone], x: cx - d / 2, y: LINE_Y - d / 2, w: d, h: d, objectName: dot });
    a4(dot, "zoom", t, 500);
    a4(T(String(i + 1), { x: cx - 0.25, y: LINE_Y - 0.2, w: 0.5, h: 0.4, fontSize: 15, bold: true, color: C.text1, align: "center", valign: "middle" }), "fade", t + 150);
    a4(T(title, { x: cx - 1.15, y: LINE_Y + 0.75, w: 2.3, h: 0.45, fontSize: 21, bold: true, color: SCHEME[tone], align: "center" }), "float", t + 100);
    a4(T(body, { x: cx - 1.15, y: LINE_Y + 1.25, w: 2.3, h: 1.0, fontSize: 13.5, color: C.background2, align: "center" }), "fade", t + 200);
  });
  a4(pulse(0.7, 5.5, 11.93, 0.75), "wipe", 1900, 1500);
  a4(T("make demo   ·   aucune main sur le clavier entre ② et ⑤   ·   Clip Chrono ≤ 60 s, sans coupe",
    { x: 0.7, y: 6.4, w: 11.93, h: 0.3, fontSize: 12.5, color: C.accent5 }), "fade", 2600);
  s.addNotes("[2:30 – 3:30] C'est exactement ce que vous verrez en direct. make demo observe et prouve, il n'exécute aucune action corrective. Personne ne touche au clavier côté hôte entre l'attaque et la preuve.");

  // ================================================================ 5 à 10. Un membre par slide
  pres.addSection({ title: "Qui a fait quoi" });
  TEAM.forEach((m, i) => {
    newSlide("CONTENU", "Qui a fait quoi");
    kickTitle(`L'ÉQUIPE · ${i + 1} / ${TEAM.length}`, m.name);
    const a = group("auto");
    a(avatar(1.35, 2.35, 2.3, m, i, 54), "zoom", 0, 700);
    a(T(m.role, { x: 0.7, y: 5.25, w: 4.2, h: 0.35, fontFace: MONO, fontSize: 14, color: SCHEME[m.tone], charSpacing: 3 }), "fade", 300);
    a(T(m.tagline, { x: 0.7, y: 5.68, w: 4.2, h: 1.0, fontSize: 17, italic: true, color: C.background2 }), "float", 450);
    m.items.forEach(([ic, tone, title, body], k) => {
      const y = 1.95 + k * 1.6, t = 600 + k * 260;
      a(card(5.6, y, 7.03, 1.4), "float", t);
      a(badge(5.95, y + 0.33, 0.74, ic, tone), "zoom", t + 120);
      a(T(title, { x: 6.98, y: y + 0.25, w: 5.4, h: 0.42, fontSize: 19, bold: true }), "fade", t + 160);
      a(T(body, { x: 6.98, y: y + 0.7, w: 5.4, h: 0.55, fontSize: 14.5, color: C.accent5 }), "fade", t + 160);
    });
    const start = 3.5 + i;
    s.addNotes(`[${Math.floor(start)}:${start % 1 ? "30" : "00"} – ${Math.floor(start + 1)}:${(start + 1) % 1 ? "30" : "00"}] ${m.name} se présente : son rôle, puis ses trois réalisations, en une minute.`);
  });

  // ================================================================ 11. Clôture
  pres.addSection({ title: "Démonstration" });
  newSlide("HEROS", "Démonstration");
  const a11 = group("auto");
  a11(T("À VOUS DE JUGER", { x: 0.9, y: 1.1, w: 9, h: 0.35, fontFace: MONO, fontSize: 14, color: C.accent1, charSpacing: 4 }), "fade");
  a11(T("Place à la démo", { x: 0.9, y: 1.55, w: 11.5, h: 1.25, fontSize: 66, bold: true }), "float", 150, 800);
  a11(T("Attaque depuis le PC Attaquant, détection, reprise, preuve — sans toucher au clavier.",
    { x: 0.9, y: 2.85, w: 11, h: 0.5, fontSize: 20, color: C.background2 }), "float", 400, 800);
  a11(pulse(0, 3.6, 13.333, 1.1), "wipe", 700, 1600);
  TEAM.forEach((m, i) => {
    const x = 0.9 + i * 1.95;
    a11(avatar(x + 0.55, 5.05, 0.7, m, i, 16), "zoom", 1500 + i * 120, 450);
    a11(T(m.name, { x, y: 5.95, w: 1.8, h: 0.35, fontSize: 13, bold: true, align: "center" }), "fade", 1600 + i * 120);
  });
  s.addNotes("[9:30 – 10:00] Remercier, puis basculer sur la démo live : attaque depuis le PC Attaquant, personne ne touche au clavier côté hôte.");

  // ---------------------------------------------------------------- écriture, thème, animations
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  await animate(OUT, SPEC);
  console.log(`PPTX : ${OUT} (${pres.slides.length} slides)`);
})().catch((e) => { console.error(e); process.exit(1); });
