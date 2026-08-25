/**
 * Scenario one: sign in, reload the page, and still be signed in.
 *
 * This is the test the whole bootstrap design exists to pass, and it is red by construction if any
 * part of that design is wrong. A reload throws away every JavaScript value this application has
 * — the access token included, because it is deliberately held in a closure and nowhere else — so
 * the only thing that can carry a session across it is the httpOnly refresh cookie plus the one
 * blocking exchange `main.ts` performs before `app.mount()`. Move that exchange after the mount,
 * or let the router's guard decide before `auth.ready`, and the first navigation of the reload
 * reads an empty store and sends a signed-in person to the login page.
 *
 * No unit test can cover this. The cookie's `SameSite=Lax`, its `Path=/api/auth` scope, its
 * `httpOnly` flag, rotation on the server, and the order in which a browser tears a page down and
 * builds it again are all browser behaviour, and a fake fetch would happily agree with itself
 * about every one of them.
 *
 * WHAT IS ASSERTED, AND WHY EACH ASSERTION IS NOT OPTIONAL
 *
 *   the URL is still the dashboard  — the failure this scenario is named for
 *   the dashboard shows the email   — the URL surviving while the page renders nothing signed-in
 *                                     would be a redirect that has not happened yet
 *   a refresh request really went   — without observing it, this test would pass just as green
 *                                     over an implementation that kept the access token in
 *                                     localStorage and never refreshed at all
 *   both storages hold no token     — which is that same regression, asserted from the other side
 *                                     and named: a token in storage outlives the tab, is readable
 *                                     by any injected script, and cannot be revoked by closing
 *                                     the browser
 *
 * Two more tests guard the only page a stranger can reach. They cost a few seconds and they cover
 * the two ways that page is normally broken: a refusal that says too much, and a `next` parameter
 * that is dropped so that everyone who follows a deep link lands on the dashboard instead of the
 * thing they clicked.
 *
 * ORDER MATTERS IN THIS FILE, and it is why `workers: 1` is not only about the rate limiter's IP
 * ceiling. The login limiter allows five failures per email per fifteen minutes and a successful
 * sign-in resets that counter. The wrong-password test spends exactly one failure, and the test
 * after it signs in successfully and hands the count back. Run these in parallel, or add a second
 * failing test beside them, and a suite run in a loop would eventually go red as `429` — which
 * this file words as its own sentence rather than "email or password is incorrect", so that the
 * failure at least says what it is.
 */

import { expect, test, type Locator, type Page, type Request } from '@playwright/test'

// The `.ts` extension is required and not a slip: this project is `"module": "nodenext"`
// (tsconfig.node.json), where an extensionless relative import does not resolve.
import { account } from '../playwright.config.ts'

/** The one protected route. Everything below asks for it by path rather than by title, because
 *  the assertion is about the address the browser is at. */
const DASHBOARD = '/'

/** A deep link into that route: the dashboard with something in the query string. The query is
 *  what makes the `next` assertions meaningful — a bare `/` would also be the fallback the login
 *  page uses when `next` is missing, so preserving it and dropping it would look identical. */
const DEEP_LINK = '/?panel=session'

/** A JWT as it appears on the wire. Used only to say that nothing shaped like one is in storage,
 *  so the check still holds if a future access token is stored under some innocent key. */
const LOOKS_LIKE_A_JWT = /eyJ[\w-]+\.[\w-]+\./

function isRefresh(request: Request): boolean {
  return request.method() === 'POST' && new URL(request.url()).pathname === '/api/auth/refresh'
}

async function signIn(page: Page, password: string = account.password): Promise<void> {
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  // By role, not by text: `Sign in` is also the heading of this page, and a text locator would
  // match two elements and fail for a reason that has nothing to do with the session.
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}

/** The email as the dashboard prints it. */
function signedInAs(page: Page): Locator {
  return page.getByText(account.email, { exact: true })
}

/** The two web storages and `document.cookie`, read from inside the page.
 *
 *  The shapes are declared here rather than imported because the end-to-end project is typed for
 *  Node (see `tsconfig.node.json`): `localStorage` and `document` are not names in this file, and
 *  pulling the DOM library in to make them names would also make every typo at the top level of a
 *  spec — `document.querySelector` in the Node half — a thing that type-checks and then fails at
 *  runtime. The callback below is transpiled before it is sent to the browser, so these
 *  annotations exist only here. */
type WebStorage = {
  readonly length: number
  key(index: number): string | null
  getItem(key: string): string | null
}

type StorageDump = {
  local: Record<string, string>
  session: Record<string, string>
  /** Everything script can read of the cookie jar. The refresh cookie must not be in it. */
  cookie: string
}

async function readStorage(page: Page): Promise<StorageDump> {
  return page.evaluate(() => {
    const scope = globalThis as unknown as {
      localStorage: WebStorage
      sessionStorage: WebStorage
      document: { cookie: string }
    }

    const dump = (store: WebStorage): Record<string, string> => {
      const entries: Record<string, string> = {}
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index)
        if (key === null) continue
        entries[key] = store.getItem(key) ?? ''
      }
      return entries
    }

    return {
      local: dump(scope.localStorage),
      session: dump(scope.sessionStorage),
      cookie: scope.document.cookie,
    }
  })
}

test('the session survives a reload, through a real refresh, with no token in storage', async ({
  page,
}) => {
  // The access token, taken off the wire. Holding the actual string is what turns "no token in
  // storage" from a guess about key names into a search for the exact secret.
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/auth/login' &&
      response.request().method() === 'POST',
  )

  await page.goto('/login')
  await signIn(page)

  const accessToken = ((await (await login).json()) as { accessToken: string }).accessToken
  expect(accessToken, 'the login response must carry an access token').not.toBe('')

  await expect(page).toHaveURL(DASHBOARD)
  await expect(signedInAs(page)).toBeVisible()

  // The cookie as it was issued at login. Its value is compared with the one that exists after the
  // reload: the server rotates on every refresh, so a changed value is the server's own account of
  // the same exchange the request listener below watches from the client's side.
  const beforeReload = await page.context().cookies()
  const issued = beforeReload.find((cookie) => cookie.name === 'sa_refresh')
  expect(issued, 'signing in must set the sa_refresh cookie').toBeTruthy()
  expect(issued?.httpOnly, 'the refresh cookie must be httpOnly').toBe(true)
  // Scoped, so the refresh token is not attached to every request the panel makes. If this ever
  // widened to `/`, the session would keep working and the test would be the only thing to notice.
  expect(issued?.path, 'the refresh cookie must be scoped to /api/auth').toBe('/api/auth')
  expect(issued?.sameSite, 'the refresh cookie must be SameSite=Lax').toBe('Lax')

  // Observed from here on: every refresh the browser sends, and every address the page visits.
  const refreshes: Request[] = []
  const visited: string[] = []
  page.on('request', (request) => {
    if (isRefresh(request)) refreshes.push(request)
  })
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) visited.push(new URL(frame.url()).pathname)
  })

  const refreshed = page.waitForResponse((response) => isRefresh(response.request()))
  await page.reload()
  await refreshed

  // THE ASSERTION THIS FILE EXISTS FOR.
  await expect(page).toHaveURL(DASHBOARD)
  expect(page.url(), 'a reload must not send a signed-in person to the login page').not.toContain(
    '/login',
  )
  // And not even for a moment. A guard that decided before `auth.ready` and corrected itself once
  // the bootstrap answered would leave the URL right and still flash the login form at somebody.
  expect(visited, 'the login page must not appear at any point during the reload').not.toContain(
    '/login',
  )

  await expect(signedInAs(page)).toBeVisible()

  // It really was a refresh that carried the session, not a token found lying around.
  expect(
    refreshes.length,
    'the reload must exchange the refresh cookie for a new access token',
  ).toBeGreaterThan(0)

  const afterReload = await page.context().cookies()
  const rotated = afterReload.find((cookie) => cookie.name === 'sa_refresh')
  expect(rotated, 'the refresh cookie must still be there after the reload').toBeTruthy()
  expect(rotated?.value, 'the server must rotate the refresh token on every exchange').not.toBe(
    issued?.value,
  )

  // THE OTHER ASSERTION THIS FILE EXISTS FOR: the token lives in memory and nowhere else.
  const storage = await readStorage(page)

  // Deliberately "empty", not "holds no token". A list of what this application is allowed to
  // persist is reviewable; a list of what it is forbidden to persist is not. The day something
  // legitimate wants a key here, this line is where that gets argued for.
  expect(Object.keys(storage.local), 'localStorage must be empty').toEqual([])
  expect(Object.keys(storage.session), 'sessionStorage must be empty').toEqual([])

  // Said again against the actual secret, so that the check survives whatever the empty assertion
  // above is one day relaxed into.
  const persisted = JSON.stringify(storage)
  expect(persisted, 'the access token must never be written to storage').not.toContain(accessToken)
  expect(persisted, 'nothing shaped like a JWT may be written to storage').not.toMatch(
    LOOKS_LIKE_A_JWT,
  )

  // The refresh token, from the only side that matters: what a script on this page can read.
  expect(storage.cookie, 'the refresh cookie must be unreadable from script').not.toContain(
    'sa_refresh',
  )
})

test('a wrong password says the one sentence and stays on the login page', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'this-is-not-the-password')

  // The backend answers an unknown address, a wrong password and a deactivated account with
  // byte-identical 401s, and goes to real trouble to do so. One sentence for the whole family is
  // what keeps the only public page in this project from being an oracle for enumerating users.
  //
  // Asserted as exact text rather than a substring for a second reason: when the login limiter has
  // been reached the page says something else entirely, and this fails as "expected 'Email or
  // password is incorrect.', got 'Too many attempts…'" instead of quietly passing on the wrong
  // refusal.
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect.')

  await expect(page).toHaveURL('/login')
  expect(await readStorage(page), 'a refused sign-in must leave nothing behind').toMatchObject({
    local: {},
    session: {},
  })
})

test('a deep link taken while anonymous is what signing in arrives at', async ({ page }) => {
  await page.goto(DEEP_LINK)

  // The guard's redirect, with the whole intended path — query string included — carried in
  // `next`. Read through `URL` rather than matched as a literal, because how vue-router percent-
  // encodes a query value is its business and not this test's.
  await expect(page).toHaveURL(
    (url) => url.pathname === '/login' && url.searchParams.get('next') === DEEP_LINK,
  )
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()

  await signIn(page)

  // Arrived at the page that was actually asked for. If `next` were dropped this would land on
  // `/` — the fallback — which is why the deep link carries a query string that the fallback
  // cannot produce.
  await expect(page).toHaveURL((url) => url.pathname === '/' && url.search === '?panel=session')
  await expect(signedInAs(page)).toBeVisible()
})
