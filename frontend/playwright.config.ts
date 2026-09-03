/**
 * Playwright, for the one scenario that no other test can cover: sign in, reload the page, and
 * still be signed in. Everything that makes that work — the httpOnly refresh cookie, its
 * `SameSite=Lax` attribute, its `Path=/api/auth` scope, the blocking bootstrap before mount — is
 * browser behaviour, and a unit test with a fake fetch would agree with itself about all of it.
 *
 * THE BROWSER MUST SEE ONE ORIGIN, exactly as it does in production behind Caddy. So the pages
 * are served by `vite preview` with the same `/api` proxy the dev server uses (both are declared
 * in vite.config.ts), and the API answers on 127.0.0.1:8000 behind it. Two origins here would
 * exercise cookie rules that never ship, and the difference would only show up in production.
 *
 * The built SPA, not the dev server: production ships `vite build` output, and index.html, the
 * hashed bundles and the history fallback are all part of what the session has to survive.
 *
 * The API is NOT started from here. It needs a database, migrations, a permission catalogue and
 * an account, and a webServer entry that quietly did all that would be a second, undocumented
 * deploy procedure. CI starts it (see .github/workflows/ci.yml); locally it is the same uvicorn
 * the README tells you to run.
 */

import { defineConfig, devices } from '@playwright/test'

/** Where `vite preview` listens, and therefore the only origin the browser ever sees. */
const port = Number(process.env['E2E_PORT'] ?? 4173)
const baseURL = `http://127.0.0.1:${port}`

/** The account the scenario signs in as.
 *
 *  CI creates it with `substate-admin create-user` against a throwaway database and passes both
 *  values in. Locally the defaults are what the README's `create-user` line uses, so a checkout
 *  can run `npm run test:e2e` without exporting anything first. */
export const account = {
  email: process.env['E2E_EMAIL'] ?? 'e2e@substate-admin.test',
  password: process.env['E2E_PASSWORD'] ?? 'playwright-local-password',
} as const

/** The second account, and it exists for one scenario: a permission is not held, and both halves
 *  of that — the control that is not drawn and the endpoint that refuses — are asserted against
 *  the same running service. A `viewer` has every `*.read` code except `users` and `audit`. */
export const viewer = {
  email: process.env['E2E_VIEWER_EMAIL'] ?? 'e2e-viewer@substate-admin.test',
  password: process.env['E2E_VIEWER_PASSWORD'] ?? 'playwright-local-password',
} as const

/** The third, which holds `users.read` and not `users.write`: the sharper half of the same rule,
 *  where the screen opens and the controls on it do not exist. */
export const support = {
  email: process.env['E2E_SUPPORT_EMAIL'] ?? 'e2e-support@substate-admin.test',
  password: process.env['E2E_SUPPORT_PASSWORD'] ?? 'playwright-local-password',
} as const

export default defineConfig({
  testDir: './e2e',

  // `.only` is a debugging aid that must never be committed: it turns a suite into one test and
  // reports green for everything it skipped.
  forbidOnly: !!process.env['CI'],

  // One retry in CI, and it exists for the trace rather than for the pass: `trace: 'on-first-retry'`
  // records nothing on the first attempt, so a flake that is never retried is a flake with no
  // evidence. Locally a failure is reproducible at the keyboard, so there is no retry at all.
  retries: process.env['CI'] ? 1 : 0,

  // One worker, deliberately. The login rate limiter lives in the API process's memory and keys
  // on the client IP; parallel workers signing in as the same account from the same address would
  // race towards that limit and fail as "invalid credentials", which is the single most misleading
  // way this suite could ever go red.
  workers: 1,

  timeout: 30_000,
  expect: { timeout: 10_000 },

  reporter: process.env['CI']
    ? [['github'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  // Chromium alone. This scenario is about cookies and navigation, not rendering, and a browser
  // matrix here would triple the slowest job in the pipeline to re-prove the same thing.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: {
    // The build is part of the command so that `npx playwright test` is self-contained wherever it
    // runs: no "did you build first?" failure that presents itself as a stale page. `--strictPort`
    // so a port already in use fails here instead of silently serving from somewhere else.
    //
    // `--host 127.0.0.1` is not decoration. Left alone, `vite preview` binds the name `localhost`,
    // which on macOS resolves to ::1 and nothing else — the server comes up, says "Local:
    // http://localhost:4173", and every request to the 127.0.0.1 below is refused. Naming the
    // address makes the thing it listens on and the thing the browser asks for the same string.
    command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env['CI'],
    timeout: 120_000,
    // Piped, not swallowed: when the build is what failed, its output is the only thing that says
    // so, and a bare "webServer did not start" would send the reader to the wrong file.
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
