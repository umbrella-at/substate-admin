/**
 * The demonstration, from the button a stranger presses to the world moving under them.
 */

/* Everything here runs with NO ACCOUNT. That is the scenario: most people who ever see this panel
   arrive by pressing one button on the login page, and every screen they then reach is served
   from a world built for them a second earlier. */

/* The clock is the reason the demonstration exists at all — a subscription engine's whole subject
   is time passing — so the assertion that matters is not that the button answers 200. It is that
   the table on screen is different afterwards. */

import { expect, test, type Page } from '@playwright/test'

const CLOCK = '/api/clock/advance'

async function tryTheDemo(page: Page): Promise<void> {
  const opened = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/demo/session' &&
      response.request().method() === 'POST',
  )

  await page.goto('/login')
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()

  const answer = await opened
  expect(answer.status(), await answer.text()).toBe(200)
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()
}

/** How many subscribers the table says there are, read off the pager's own count. */
async function total(page: Page): Promise<number> {
  const page_ = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/subscribers',
  )
  await page.goto('/subscribers')
  const body = (await (await page_).json()) as { total: number }
  await expect(page.locator('tbody tr').first()).toBeVisible()
  return body.total
}

test.describe('a stranger with no account', () => {
  let page: Page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await tryTheDemo(page)
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('is given a world with a history already in it', async () => {
    expect(await total(page)).toBeGreaterThan(300)
  })

  test('is shown operators of its own, invented for this world', async () => {
    // Decision 85, on screen. A demonstration visitor holds `users.read` because the table is
    // filtered by world: these are colleagues the sandbox made up, and nobody real is among them.
    await page.goto('/users')
    await expect(page.getByRole('link', { name: 'Users and roles' })).toBeVisible()
    await expect(page.getByText('you@example.com').first()).toBeVisible()
  })

  test('can wind the clock, and the table is different afterwards', async () => {
    const before = await total(page)

    const wound = page.waitForResponse(
      (response) => new URL(response.url()).pathname === CLOCK && response.status() === 200,
    )
    await page.getByRole('button', { name: 'Month', exact: true }).click()
    await wound

    // Not merely "the request succeeded". A world that is only ticked forward loses most of its
    // paying subscribers; one that goes on living gains people. The direction is the assertion.
    await expect(async () => {
      expect(await total(page)).toBeGreaterThan(before)
    }).toPass()
  })

  test('says how far the world has been wound', async () => {
    await expect(page.getByText(/\d+ days ahead of today/u)).toBeVisible()
  })
})

test.describe('the clock control', () => {
  test('is not drawn for somebody who may not drive it', async ({ page }) => {
    // `viewer` holds every read this panel has except two, and not `demo.control`. The control is
    // absent rather than disabled, which is the same rule every nav link follows.
    const { viewer } = await import('../playwright.config.ts')
    await page.goto('/login')
    await page.getByLabel('Email', { exact: true }).fill(viewer.email)
    await page.getByLabel('Password', { exact: true }).fill(viewer.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()

    await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'World clock' })).toHaveCount(0)
  })
})
