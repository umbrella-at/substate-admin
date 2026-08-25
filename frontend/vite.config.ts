import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
// `defineConfig` from vitest/config, not from vite: it is vite's own function with the `test`
// section added to its type. Imported from vite, the block below is an object literal with an
// unknown property, and `vue-tsc --build` says so.
import { defineConfig } from 'vitest/config'

/** Everything under /api belongs to the API process; nothing else does. `changeOrigin: false`
 *  leaves the Host header alone, so the API sees the origin the browser typed. */
const apiProxy = {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: false,
  },
}

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

  // The browser must see ONE origin, exactly as it does in production behind Caddy. That is not
  // tidiness: the refresh cookie is SameSite=Lax and scoped to /api/auth, so a cross-origin setup
  // would exercise different cookie rules than the ones that ship — and the session would break in
  // production only. It also means no CORS middleware exists anywhere in this project.
  //
  // Declared once and given to both servers. `preview` does NOT inherit `server.proxy`: it is a
  // separate config section, and leaving it out would give the end-to-end run — the one place the
  // built SPA is exercised by a real browser — the two-origin setup this whole arrangement exists
  // to avoid.
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },

  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
    globals: false,
  },
})
