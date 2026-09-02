/**
 * One subscriber, in a browser, against the real service.
 *
 * The unit tests know what an operation is supposed to answer; this is where that belief meets the
 * engine. What only exists once there is a browser is the whole path: press a button, and the card
 * moves, the feed gains the event the engine emitted, and the audit gains the row somebody will
 * one day look for.
 *
 * NO SUBSCRIBER IS NAMED. The base world runs on a live clock and the ticker crosses boundaries
 * every thirty seconds, so `sub-0007` is in grace on one run and expired on the next. The subject
 * is chosen at runtime from a filtered table, and what is asserted is the shape of the card rather
 * than the identity in it.
 */

import { expect, test, type Page } from '@playwright/test'

import { account } from '../playwright.config.ts'

// One sign-in for the whole file, for the reason the table's suite records: the login throttle is
// right and a test that signs in a dozen times is wrong.
test.describe.configure({ mode: 'serial' })

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()
}

/** Open the card of whoever is first under this filter, and return their id.
 *
 *  The filter is how the subject is chosen without naming one: `?state=active` is a question the
 *  world answers differently every run and always with somebody. */
async function openFirst(page: Page, state: string): Promise<string> {
  await page.goto(`/subscribers?state=${state}`)
  const first = page.locator('tbody tr').first()
  await expect(first).toBeVisible()
  const id = (await first.locator('td').first().innerText()).split('\n').at(-1)?.trim() ?? ''
  await first.getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/subscribers/${id}$`))
  return id
}

test.describe('a subscriber card', () => {
  let page: Page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await signIn(page)
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('is reached from the name in the table', async () => {
    const id = await openFirst(page, 'active')

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByText(id, { exact: true }).first()).toBeVisible()
  })

  // The boundary an ACTIVE subscription has, and the two it does not. A card with three date rows
  // would pass a check that the right one is present; this one cannot.
  test('draws the boundary this state owns and no others', async () => {
    await openFirst(page, 'active')

    await expect(page.getByText('Expires', { exact: true })).toBeVisible()
    await expect(page.getByText('Trial ends', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Grace ends', { exact: true })).toHaveCount(0)
  })

  test('shows a history with a sentence in every row', async () => {
    await openFirst(page, 'active')

    const feed = page.locator('table').last().locator('tbody tr')
    await expect(feed.first()).toBeVisible()
    // Three cells, and the third is a sentence rather than the payload it was built from.
    await expect(feed.first().locator('td')).toHaveCount(3)
    await expect(feed.first().locator('td').last()).not.toHaveText(/[{}]/u)
  })

  // The whole path, and the reason the round exists: press the button, and the engine moves, the
  // feed records it and the audit records who asked.
  test('an operation moves the card, the feed and the audit', async () => {
    const id = await openFirst(page, 'active')
    const reference = `e2e-${Date.now()}`

    await page.getByLabel('Reference (optional)').fill(reference)
    await page.getByRole('button', { name: 'Record a payment' }).click()

    await expect(page.getByRole('status')).toContainText('was recorded')
    await expect(page.locator('table').last()).toContainText('payment.recorded')

    await page.goto(`/audit?targetId=${id}`)
    await expect(page.getByRole('table')).toContainText('Recorded a payment')
    await expect(page.getByRole('table')).toContainText(reference)
  })

  // A reference already on file is a 200 that changed nothing, and the panel has to say so rather
  // than repeat what the button promised.
  test('a repeated reference says nothing changed', async () => {
    await openFirst(page, 'active')
    const reference = `e2e-twice-${Date.now()}`

    await page.getByLabel('Reference (optional)').fill(reference)
    await page.getByRole('button', { name: 'Record a payment' }).click()
    await expect(page.getByRole('status')).toContainText('was recorded')

    await page.getByRole('button', { name: 'Record a payment' }).click()

    await expect(page.getByRole('status')).toContainText('Nothing changed.')
  })

  // A refusal from the engine, named by the code the specification fixes and put under the input
  // that caused it.
  test('an unknown promo code is refused under the field it came from', async () => {
    await openFirst(page, 'active')

    await page.getByLabel('Promo code', { exact: true }).fill('NO-SUCH-CODE')
    await page.getByRole('button', { name: 'Redeem code' }).click()
    // Scoped to the dialog. The trigger keeps its name and sits under the scrim, so an unscoped
    // locator finds the button nobody can press.
    await page.getByRole('alertdialog').getByRole('button', { name: 'Redeem code' }).click()

    await expect(page.getByRole('alert')).toHaveText('No promo code is registered under that code.')
  })

  // The pause before something nothing can undo, and the two buttons that name what they do.
  test('cancelling asks first, and both answers name themselves', async () => {
    await openFirst(page, 'active')

    await page.getByRole('button', { name: 'Cancel subscription' }).click()

    await expect(page.getByRole('alertdialog')).toContainText('Renewal will not be attempted.')
    await expect(page.getByRole('button', { name: 'Keep subscription' })).toBeVisible()
    // Never a button labelled `Cancel` on this dialog: one word for two opposite actions.
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0)

    await page.getByRole('button', { name: 'Keep subscription' }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
  })

  // A link from before a restart names somebody the rebuilt world does not have. It is an answer,
  // not a failure, and it offers the way back rather than the same attempt again.
  test('a subscriber who does not exist is said to be missing', async () => {
    await page.goto('/subscribers/nobody-at-all')

    await expect(page.getByText('There is no subscriber')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Back to subscribers' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0)
  })
})
