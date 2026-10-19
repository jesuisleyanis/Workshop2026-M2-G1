/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev : le navigateur ouvre le flux SSE en same-origin sur /remediation/stream ; Vite
// proxifie vers REMEDIATION_PROXY_TARGET (par défaut http://localhost:8005, ou le mock
// `npm run mock`) en retirant le préfixe /remediation.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.REMEDIATION_PROXY_TARGET || 'http://localhost:8005'
  return {
    base: './',
    plugins: [react(), tailwindcss()],
    server: {
      host: '0.0.0.0',
      port: 5174,
      strictPort: true,
      proxy: {
        '/remediation': {
          target,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/remediation/, ''),
        },
        // UI de l'assistant RAG (onglet iframe) : /assistant/* -> ASSISTANT_PROXY_TARGET/*.
        '/assistant': {
          target: env.ASSISTANT_PROXY_TARGET || 'http://localhost:8006',
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/assistant/, ''),
        },
      },
    },
    preview: { host: '0.0.0.0', port: 5174 },
    build: { sourcemap: false, target: 'es2022' },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  }
})
