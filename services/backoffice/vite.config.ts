/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Le back-office est servi derrière le WAF ; il appelle /api/v1/auth/* en same-origin.
// En dev direct (sans WAF), on proxifie vers le service auth (DEV_AUTH_TARGET).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.DEV_AUTH_TARGET || 'http://localhost:8002'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: '0.0.0.0',
      port: 5174,
      strictPort: true,
      proxy: { '/api': { target, changeOrigin: true } },
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
