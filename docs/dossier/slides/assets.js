// Visuels du deck générés à la volée (aucun fichier binaire commité) : fonds, ligne de pouls, icônes.
// SVG -> PNG via sharp ; les icônes viennent de react-icons (Lucide).
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const lu = require("react-icons/lu");

const PALETTE = {
  ink: "0B1220",
  dot: "1B2740",
  mint: "2EE6A6",
  coral: "FF5A5F",
  amber: "FFB547",
  blue: "5B8CFF",
};

const toData = (buf) => "image/png;base64," + buf.toString("base64");

// Fond 16:9 : encre profonde, grille de points, deux halos (un pour le contenu, plus marqué pour les slides « héros »).
async function background(kind) {
  const W = 1920, H = 1080;
  const strong = kind === "hero";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
  <defs>
    <pattern id="dots" width="32" height="32" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.4" fill="#${PALETTE.dot}"/>
    </pattern>
    <radialGradient id="g1" cx="${strong ? 0.78 : 0.92}" cy="${strong ? 0.22 : 0.05}" r="${strong ? 0.6 : 0.5}">
      <stop offset="0" stop-color="#${PALETTE.mint}" stop-opacity="${strong ? 0.22 : 0.10}"/>
      <stop offset="1" stop-color="#${PALETTE.mint}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="g2" cx="${strong ? 0.12 : 0.02}" cy="${strong ? 0.92 : 1.0}" r="${strong ? 0.55 : 0.45}">
      <stop offset="0" stop-color="#${PALETTE.blue}" stop-opacity="${strong ? 0.20 : 0.09}"/>
      <stop offset="1" stop-color="#${PALETTE.blue}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#${PALETTE.ink}" stop-opacity="0"/>
      <stop offset="1" stop-color="#${PALETTE.ink}" stop-opacity="0.85"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="#${PALETTE.ink}"/>
  <rect width="100%" height="100%" fill="url(#dots)" opacity="${strong ? 0.9 : 0.55}"/>
  <rect width="100%" height="100%" fill="url(#fade)"/>
  <rect width="100%" height="100%" fill="url(#g1)"/>
  <rect width="100%" height="100%" fill="url(#g2)"/>
</svg>`;
  return toData(await sharp(Buffer.from(svg)).png().toBuffer());
}

// Ligne de pouls : service sain (menthe) -> attaque (corail) -> détection (ambre) -> reprise (menthe), avec halo.
async function pulse({ width = 2400, height = 300, stroke = 6 } = {}) {
  const y = height / 2;
  const sx = width / 2400;
  const pts = [
    [0, y], [620, y], [650, y - 18], [680, y], [880, y], [930, y - 120], [985, y + 115], [1035, y - 70],
    [1075, y], [1160, y], [1190, y - 22], [1220, y], [1420, y], [1450, y - 14], [1480, y], [2400, y],
  ].map(([px, py]) => `${(px * sx).toFixed(1)},${py.toFixed(1)}`);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
  <defs>
    <linearGradient id="s" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#${PALETTE.mint}" stop-opacity="0.15"/>
      <stop offset="0.30" stop-color="#${PALETTE.mint}"/>
      <stop offset="0.39" stop-color="#${PALETTE.coral}"/>
      <stop offset="0.44" stop-color="#${PALETTE.amber}"/>
      <stop offset="0.52" stop-color="#${PALETTE.mint}"/>
      <stop offset="1" stop-color="#${PALETTE.mint}" stop-opacity="0.15"/>
    </linearGradient>
    <filter id="glow" x="-5%" y="-50%" width="110%" height="200%">
      <feGaussianBlur stdDeviation="${stroke * 1.6}" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <polyline points="${pts.join(" ")}" fill="none" stroke="url(#s)" stroke-width="${stroke}"
            stroke-linejoin="round" stroke-linecap="round" filter="url(#glow)"/>
</svg>`;
  return toData(await sharp(Buffer.from(svg)).png().toBuffer());
}

async function icon(name, color, size = 256) {
  const Comp = lu[name];
  if (!Comp) throw new Error(`icône inconnue : ${name}`);
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  return toData(await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer());
}

module.exports = { PALETTE, background, pulse, icon };
