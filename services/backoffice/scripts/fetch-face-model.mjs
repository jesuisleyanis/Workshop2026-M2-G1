#!/usr/bin/env node
// Prépare les assets du détecteur de pose (MediaPipe Face Landmarker), servis par le
// back-office lui-même (aucun CDN : CSP 'self') :
//   - public/models/face_landmarker.task : téléchargé puis VÉRIFIÉ par sha256 (figé ci-dessous) ;
//   - public/mediapipe/*                 : runtime wasm copié depuis node_modules.
// Idempotent : un modèle déjà présent et intègre n'est pas retéléchargé.
// Usage : npm run prepare:vision   (exécuté aussi par le Dockerfile avant le build).
import { createHash } from 'node:crypto'
import { copyFile, mkdir, readdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
// Empreinte du modèle float16/1, calculée au premier téléchargement (2026-10-20).
const MODEL_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const modelsDir = join(root, 'public', 'models')
const modelPath = join(modelsDir, 'face_landmarker.task')
const wasmSrc = join(root, 'node_modules', '@mediapipe', 'tasks-vision', 'wasm')
const wasmDst = join(root, 'public', 'mediapipe')

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex')

async function existingIsValid() {
  try {
    return sha256(await readFile(modelPath)) === MODEL_SHA256
  } catch {
    return false
  }
}

async function fetchModel() {
  await mkdir(modelsDir, { recursive: true })
  if (await existingIsValid()) {
    console.log('[prepare:vision] modèle déjà présent et intègre')
    return
  }
  console.log(`[prepare:vision] téléchargement ${MODEL_URL}`)
  const res = await fetch(MODEL_URL)
  if (!res.ok) throw new Error(`téléchargement du modèle : HTTP ${res.status}`)
  const buf = Buffer.from(await res.arrayBuffer())
  const got = sha256(buf)
  if (got !== MODEL_SHA256) {
    throw new Error(`sha256 du modèle inattendu : ${got} (attendu ${MODEL_SHA256})`)
  }
  // Écriture atomique : jamais de modèle partiel servi.
  const tmp = `${modelPath}.part`
  await writeFile(tmp, buf)
  await rename(tmp, modelPath)
  console.log(`[prepare:vision] modèle vérifié (${buf.length} octets)`)
}

async function copyWasm() {
  await rm(wasmDst, { recursive: true, force: true })
  await mkdir(wasmDst, { recursive: true })
  const files = await readdir(wasmSrc)
  for (const f of files) await copyFile(join(wasmSrc, f), join(wasmDst, f))
  console.log(`[prepare:vision] runtime wasm copié (${files.length} fichiers)`)
}

try {
  await fetchModel()
  await copyWasm()
} catch (err) {
  console.error(`[prepare:vision] échec : ${err instanceof Error ? err.message : err}`)
  process.exit(1)
}
