/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev : le navigateur appelle /api/v1/... en same-origin, Vite proxifie vers
// DEV_API_TARGET (par défaut le WAF local). En prod, le front est servi en statique
// derrière le WAF, qui route /api/v1/* vers auth et payment-api.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.DEV_API_TARGET || 'http://localhost'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target, changeOrigin: true } },
    },
    preview: { host: '0.0.0.0', port: 5173 },
    build: { sourcemap: false, target: 'es2022' },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  }
})
