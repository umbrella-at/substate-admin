/**
 * Both halves of one rule, against the running service: the control is not drawn, and the
 * endpoint refuses the direct call.
 */

/* Either half alone is a false comfort. A hidden button over an open endpoint is a panel that
   only looks locked; a 403 under a button that is drawn is a panel that offers a locked door. */

import { expect, test, type Page } from '@playwright/test'

import { support, viewer } from '../playwright.config.ts'

// One sign-in per account, for the reason the other files give: the login throttle counts
// attempts by address and does not forgive them on success.
test.describe.configure({ mode: 'serial' })

const ROLES = '/api/roles'

async function signIn(page: Page, as: { email: string; password: string }): Promise<string> {
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/auth/login' &&
      response.request().method() === 'POST',
  )

  await page.goto('/login')
  await page.getByLabel('Email', { exact: true }).fill(as.email)
  await page.getByLabel('Password', { exact: true }).fill(as.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()

  // The token off the wire. It never reaches storage — session.spec.ts asserts that — so this is
  // the only way to make the request a browser would have made if the control existed.
  const { accessToken } = (await (await login).json()) as { accessToken: string }
  expect(accessToken, 'the login response must carry an access token').not.toBe('')
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()
  return accessToken
}

test.describe('a viewer, who may not read the roles at all', () => {
  let page: Page
  let token: string

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    token = await signIn(page, viewer)
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('is offered no way into the screen', async () => {
    await expect(page.getByRole('link', { name: 'Users and roles' })).toHaveCount(0)
    // The sections they DO hold, so this is a filtered menu rather than a broken one.
    await expect(page.getByRole('link', { name: 'Analytics' })).toBeVisible()
  })

  test('is refused the endpoint behind it', async () => {
    const response = await page.request.get(ROLES, {
      headers: { authorization: `Bearer ${token}` },
    })

    expect(response.status()).toBe(403)
    expect(await response.json()).toEqual({
      error: {
        code: 'PERMISSION_DENIED',
        message: 'You do not have permission to do that.',
        field: null,
      },
    })
  })

  test('is told so at the address, rather than sent somewhere else', async () => {
    await page.goto('/users')

    await expect(page).toHaveURL(/\/users$/)
    await expect(page.getByText('This page is not yours to open.')).toBeVisible()
    await expect(page.getByText('users.read')).toBeVisible()
  })
})

/**
 * The sharper half: the screen opens, and the controls on it are not there. A viewer never
 * reaches the screen at all, so on its own that scenario proves nothing about a button.
 */
test.describe('support, who may read the roles and not write them', () => {
  let page: Page
  let token: string
  let roleId: string

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    token = await signIn(page, support)
    await page.getByRole('link', { name: 'Users and roles' }).click()
    await expect(page.getByRole('heading', { name: 'Roles', exact: true })).toBeVisible()

    // A CUSTOM role. Save and Delete are hidden on a system role whoever is looking, so asserting
    // their absence there would pass with the permission check deleted.
    const body = (await (
      await page.request.get(ROLES, {
        headers: { authorization: `Bearer ${token}` },
      })
    ).json()) as { items: { id: string; name: string; isSystem: boolean }[] }
    const custom = body.items.find((each) => !each.isSystem)
    expect(custom, 'the scenario needs a role that is not defined by the application').toBeDefined()
    roleId = custom!.id
    await page.getByRole('button', { name: custom!.name, exact: true }).click()
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('gets the screen and the catalogue', async () => {
    await expect(page.getByText('View aggregate analytics.')).toBeVisible()
  })

  test('is offered no control that would be refused', async () => {
    for (const control of ['New role', 'Save role', 'Delete role', 'Create role']) {
      await expect(page.getByRole('button', { name: control }), control).toHaveCount(0)
    }
  })

  test('is refused the write behind them', async () => {
    const response = await page.request.put(`${ROLES}/${roleId}`, {
      headers: { authorization: `Bearer ${token}` },
      data: { name: 'Mine now', permissions: [] },
    })

    expect(response.status()).toBe(403)
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe(
      'PERMISSION_DENIED',
    )
  })
})
