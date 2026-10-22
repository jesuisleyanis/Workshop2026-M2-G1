// Post-traitement OOXML : transitions (Morph, repli en fondu) et animations d'entrée, que pptxgenjs n'écrit pas.
// Spécification par slide (index 1-based) :
//   { transition: "morph" | "fade", groups: [{ trigger: "auto" | "click", items: [{ name, effect, delay, dur }] }] }
// `name` = objectName donné à la forme dans build.js ; effect = fade | wipe | float | zoom.
// Seul le premier groupe peut être "auto" (il démarre avec la slide) ; les suivants se déclenchent au clic.
const JSZip = require("jszip");
const fs = require("fs");

const PRESETS = { fade: [10, 0], wipe: [22, 8], float: [42, 0], zoom: [53, 16] };
const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function shapesOf(xml) {
  // nom -> { id, hasText } pour les <p:sp> et <p:pic> de premier niveau (pptxgenjs n'imbrique pas).
  const out = new Map();
  for (const m of xml.matchAll(/<p:(sp|pic)>([\s\S]*?)<\/p:\1>/g)) {
    const c = m[2].match(/<p:cNvPr id="(\d+)" name="([^"]*)"/);
    if (!c) continue;
    const name = c[2].replace(/&amp;/g, "&").replace(/&quot;/g, '"');
    out.set(name, { id: c[1], hasText: m[1] === "sp" && /<a:t>[^<]/.test(m[2]) });
  }
  return out;
}

function timingXml(groups, shapes, slideNo) {
  let id = 2;
  const next = () => ++id;
  const built = new Set();
  const tgt = (spid) => `<p:tgtEl><p:spTgt spid="${spid}"/></p:tgtEl>`;
  const anim = (spid, attr, from, to, dur) =>
    `<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="${next()}" dur="${dur}" fill="hold"/>${tgt(spid)}` +
    `<p:attrNameLst><p:attrName>${attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst>` +
    `<p:tav tm="0"><p:val>${from}</p:val></p:tav><p:tav tm="100000"><p:val>${to}</p:val></p:tav></p:tavLst></p:anim>`;
  const effect = (it, nodeType) => {
    const sh = shapes.get(it.name);
    if (!sh) throw new Error(`slide ${slideNo} : forme « ${it.name} » introuvable pour l'animation`);
    const [preset, sub] = PRESETS[it.effect];
    const dur = it.dur ?? (it.effect === "wipe" ? 600 : 350);
    if (sh.hasText) built.add(sh.id);
    let body =
      `<p:set><p:cBhvr><p:cTn id="${next()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>` +
      `${tgt(sh.id)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>` +
      `<p:to><p:strVal val="visible"/></p:to></p:set>`;
    const fadeIn = (filter) =>
      `<p:animEffect transition="in" filter="${filter}"><p:cBhvr><p:cTn id="${next()}" dur="${dur}"/>${tgt(sh.id)}</p:cBhvr></p:animEffect>`;
    if (it.effect === "fade") body += fadeIn("fade");
    if (it.effect === "wipe") body += fadeIn("wipe(left)");
    if (it.effect === "float") {
      body += fadeIn("fade");
      body += anim(sh.id, "ppt_x", '<p:strVal val="#ppt_x"/>', '<p:strVal val="#ppt_x"/>', dur);
      body += anim(sh.id, "ppt_y", '<p:strVal val="#ppt_y+0.05"/>', '<p:strVal val="#ppt_y"/>', dur);
    }
    if (it.effect === "zoom") {
      body += anim(sh.id, "ppt_w", '<p:fltVal val="0"/>', '<p:strVal val="#ppt_w"/>', dur);
      body += anim(sh.id, "ppt_h", '<p:fltVal val="0"/>', '<p:strVal val="#ppt_h"/>', dur);
      body += fadeIn("fade");
    }
    const grp = sh.hasText ? ' grpId="0"' : "";
    const ease = it.effect === "float" || it.effect === "zoom" ? ' decel="100000"' : "";
    return (
      `<p:par><p:cTn id="${next()}" presetID="${preset}" presetClass="entr" presetSubtype="${sub}" fill="hold"${grp}${ease} nodeType="${nodeType}">` +
      `<p:stCondLst><p:cond delay="${it.delay || 0}"/></p:stCondLst><p:childTnLst>${body}</p:childTnLst></p:cTn></p:par>`
    );
  };
  // Les ids des nœuds parents doivent précéder ceux des enfants : on construit en deux passes.
  const parts = groups.map((g, gi) => {
    if (g.trigger === "auto" && gi > 0) throw new Error(`slide ${slideNo} : seul le premier groupe peut être auto`);
    const outer = next(), inner = next();
    const first = g.trigger === "auto" ? "afterEffect" : "clickEffect";
    const effects = g.items.map((it, i) => effect(it, i === 0 ? first : "withEffect")).join("");
    const start = g.trigger === "auto"
      ? `<p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>`
      : `<p:cond delay="indefinite"/>`;
    return `<p:par><p:cTn id="${outer}" fill="hold"><p:stCondLst>${start}</p:stCondLst><p:childTnLst>` +
      `<p:par><p:cTn id="${inner}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>${effects}` +
      `</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>`;
  });
  const bld = [...built].map((spid) => `<p:bldP spid="${spid}" grpId="0" animBg="1"/>`).join("");
  return (
    `<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>` +
    `<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>${parts.join("")}` +
    `</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>` +
    `<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>` +
    `</p:childTnLst></p:cTn></p:par></p:tnLst>${bld ? `<p:bldLst>${bld}</p:bldLst>` : ""}</p:timing>`
  );
}

function transitionXml(kind) {
  const fade = `<p:transition spd="fast"><p:fade/></p:transition>`;
  if (kind !== "morph") return fade;
  return (
    `<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">` +
    `<mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" Requires="p159">` +
    `<p:transition xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" spd="med" p14:dur="600"><p159:morph option="byObject"/></p:transition>` +
    `</mc:Choice><mc:Fallback>${fade}</mc:Fallback></mc:AlternateContent>`
  );
}

async function animate(file, spec) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  for (const [no, s] of Object.entries(spec)) {
    const path = `ppt/slides/slide${no}.xml`;
    let xml = await zip.file(path).async("string");
    if (/<p:timing>|<p:transition/.test(xml)) throw new Error(`${path} : déjà animée`);
    const add = transitionXml(s.transition) + (s.groups.length ? timingXml(s.groups, shapesOf(xml), no) : "");
    const anchor = xml.includes("</p:clrMapOvr>") ? "</p:clrMapOvr>" : "</p:cSld>";
    xml = xml.replace(anchor, anchor + add);
    zip.file(path, xml);
  }
  const buf = await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
  fs.writeFileSync(file, buf);
}

module.exports = { animate, esc };
