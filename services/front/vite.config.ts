/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev : le navigateur appelle /api/v1/... en same-origin, Vite proxifie vers
// DEV_API_TARGET (par défaut le WAF local). En prod, le front est servi en statique
// derrière le WAF, qui route /api/v1/* vers auth et payment-api.
//
// Sans WAF local (dev direct), on peut router comme lui en pointant les endpoints
// d'auth vers le service auth : DEV_AUTH_TARGET (login/register) et DEV_API_TARGET
// (accounts/transactions, payment-api). Si DEV_AUTH_TARGET est absent, tout va sur
// DEV_API_TARGET — comportement WAF inchangé.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  // WAF local : HTTPS seulement (le port 80 ne fait plus que rediriger), certificat auto-signé.
  const target = env.DEV_API_TARGET || 'https://localhost'
  const authTarget = env.DEV_AUTH_TARGET || target
  const proxyOpts = { changeOrigin: true, secure: false }
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      strictPort: true,
      proxy: {
        // Clés les plus spécifiques d'abord (auth), fallback /api sur payment-api.
        '/api/v1/login': { target: authTarget, ...proxyOpts },
        '/api/v1/register': { target: authTarget, ...proxyOpts },
        '/api/v1/auth/': { target: authTarget, ...proxyOpts }, // step-up (#51)
        '/api': { target, ...proxyOpts },
      },
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
