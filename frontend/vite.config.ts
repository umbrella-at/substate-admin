import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],

  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },

  build: {
    // The Content-Security-Policy this application is served under is `default-src 'self'` with
    // no `unsafe-inline` for scripts, and Vite's modulePreload polyfill is injected as an inline
    // script. Every browser this targets supports modulepreload natively, so the polyfill buys
    // nothing and would cost the whole page.
    modulePreload: { polyfill: false },
  },

  server: {
    // The browser must see ONE origin in development, exactly as it does in production behind
    // Caddy. That is not tidiness: the refresh cookie is SameSite=Lax and scoped to /api/auth, so
    // a cross-origin dev setup would exercise different cookie rules than the ones that ship —
    // and the session would break in production only. It also means no CORS middleware exists
    // anywhere in this project.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },

  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
    globals: false,
  },
})
