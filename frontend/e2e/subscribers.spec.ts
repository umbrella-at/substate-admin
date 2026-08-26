/**
 * The table, in a browser, against the real service.
 *
 * The unit tests know what the API is supposed to return; this is where that belief meets what it
 * does return. The last iteration's defect was of exactly that shape — a schema that was correct
 * as code and wrong as a contract — and TypeScript believed it all the way to the screen.
 *
 * What is asserted here is the behaviour that only exists once there is a browser: that the
 * address bar carries the question, that reloading it gives the same table back, and that the
 * back button walks the filters somebody used rather than leaving the page.
 */

import { expect, test, type Page } from '@playwright/test'

import { account } from '../playwright.config.ts'

/*
 * ONE SIGN-IN FOR THE WHOLE FILE.
 *
 * Signing in per test is the tidier shape and it does not survive contact with the service: the
 * login throttle counts attempts, a dozen of them arrive in seconds, and the suite starts failing
 * with "element not found" on the page after the one that was refused. The throttle is right and
 * the test was wrong — so the session is established once and the tests share it, which is also
 * closer to what a person does.
 *
 * Serial, because they share it. Each test starts from a clean address rather than from wherever
 * the previous one left the filters.
 */
test.describe.configure({ mode: 'serial' })

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()
}

function rows(page: Page) {
  return page.locator('tbody tr')
}

test.describe('the subscriber table', () => {
  let page: Page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await signIn(page)
  })

  test.afterAll(async () => {
    await page.close()
  })

  test.beforeEach(async () => {
    await page.goto('/subscribers')
    await expect(page.locator('tbody tr').first()).toBeVisible()
  })

  test('shows a page of real subscribers', async () => {
    await expect(rows(page)).toHaveCount(25)
    await expect(page.getByText(/\d+ subscribers/)).toBeVisible()
  })

  // The row is the point of the whole screen: a name, a state anybody can recognise before
  // reading it, and the two dates somebody would act on.
  test('every row carries a state chip', async () => {
    const first = rows(page).first()
    await expect(
      first.getByText(/^(Trial|Active|In grace|Expired|Cancelled)$/),
    ).toBeVisible()
  })

  test('a filter narrows the table and says so in the address', async () => {
    await page.getByRole('checkbox', { name: 'In grace' }).click()
    await expect(page).toHaveURL(/state=grace/)
    await expect(rows(page).first().getByText('In grace')).toBeVisible()

    const total = await page.getByText(/\d+ subscribers?/).textContent()
    expect(Number(total?.match(/\d+/)?.[0])).toBeLessThan(50)
  })

  // The property that makes the URL worth putting the state in: the link is the table.
  test('the filtered table survives a reload', async () => {
    const count = page.getByText(/\d+ subscribers?/)
    const unfiltered = await count.textContent()

    await page.getByRole('checkbox', { name: 'Expired' }).click()
    await expect(page).toHaveURL(/state=expired/)
    // Waiting for the answer, not for the address: the count is the last thing to change, and
    // reading it too early compares the filtered table against the unfiltered number.
    await expect(count).not.toHaveText(unfiltered ?? '')
    const before = await count.textContent()

    await page.reload()
    await expect(page.getByRole('checkbox', { name: 'Expired' })).toBeChecked()
    await expect(count).toHaveText(before ?? '')
  })

  test('the back button walks the filters rather than leaving', async () => {
    await page.getByRole('checkbox', { name: 'Trial' }).click()
    await expect(page).toHaveURL(/state=trial/)
    await page.goBack()
    await expect(page).toHaveURL(/\/subscribers$/)
    await expect(page.getByRole('checkbox', { name: 'Trial' })).not.toBeChecked()
  })

  test('sorting is a link, and reverses on the second click', async () => {
    const header = page.getByRole('columnheader').getByRole('link', { name: 'Subscriber' })
    await header.click()
    await expect(page).toHaveURL(/sort=displayName/)
    await header.click()
    await expect(page).toHaveURL(/sort=-displayName/)
  })

  // Absent values belong at the bottom in either direction. This is the browser-side half of the
  // defect found by asking the service directly: descending order used to open with them.
  test('rows with no access boundary stay at the bottom when the order reverses', async () => {
    const header = page.getByRole('columnheader').getByRole('link', { name: 'Access until' })
    await header.click()
    await expect(page).toHaveURL(/sort=accessUntil/)
    await header.click()
    await expect(page).toHaveURL(/sort=-accessUntil/)
    await expect(rows(page).first().locator('td').nth(3)).not.toHaveText('—')
  })

  // A category header offers no order, because there is none to offer — and it offers nothing
  // else either. It was briefly a link to the filter panel, which scrolled the page a hundred
  // pixels, put nothing new on screen, and read as a control that had broken.
  test('a category header is inert, and the page does not move when it is clicked', async () => {
    const headers = page.getByRole('columnheader')
    await expect(headers.getByRole('link', { name: 'State' })).toHaveCount(0)
    await expect(headers.getByRole('link', { name: 'Plan' })).toHaveCount(0)

    // `globalThis` rather than `window`: this file is type-checked without the DOM lib, the same
    // way the session scenario reaches localStorage.
    const scrollY = () =>
      page.evaluate(() => (globalThis as unknown as { scrollY: number }).scrollY)

    const before = await scrollY()
    await headers.filter({ hasText: 'State' }).click()
    await expect.poll(scrollY).toBe(before)
  })

  // The order over states is a name, and the API decides it: in grace first, because that is a
  // paying customer whose payment failed today.
  test('the urgency order puts what needs doing at the top', async () => {
    await page.getByRole('button', { name: 'Sort by urgency' }).click()
    await expect(page).toHaveURL(/sort=state/)
    await expect(page.locator('tbody tr').first().getByText('In grace')).toBeVisible()

    // The label says what it did, not what it will do.
    await page.getByRole('button', { name: 'Sorted by urgency' }).click()
    await expect(page).toHaveURL(/\/subscribers$/)
  })

  test('more than one plan can be asked for at once', async () => {
    const count = page.getByText(/\d+ subscribers?/)

    // Exact: "annual" is also inside "semiannual", and a substring match would tick both.
    await page.getByRole('checkbox', { name: 'weekly' }).click()
    await expect(page).toHaveURL(/planId=weekly/)
    await expect(count).not.toHaveText(/351/)
    const one = Number((await count.textContent())?.match(/\d+/)?.[0])

    await page.getByRole('checkbox', { name: 'annual', exact: true }).click()
    await expect(page).toHaveURL(/planId=weekly.*planId=annual/)

    // The second plan widens the answer rather than replacing it, which is the whole difference
    // between a set and the single value this used to be.
    //
    // Polled on the number rather than waited on the text: the count also carries "· page 1 of 3",
    // so an assertion against "72 subscribers" is never equal to it and `not.toHaveText` returns
    // at once — which is how the first version of this read the old total and compared it with
    // itself.
    await expect
      .poll(async () => Number((await count.textContent())?.match(/\d+/)?.[0]))
      .toBeGreaterThan(one)

    // Whichever rows the order happens to put on this page, none of them is a third plan. The
    // earlier version of this asserted both plans were visible here, which is a fact about the
    // default order rather than about the filter, and it failed the first time that order moved.
    const plans = await page.locator('tbody tr td:nth-child(3)').allTextContents()
    for (const plan of plans) expect(['weekly', 'annual']).toContain(plan.trim())
  })

  // A subscription has three boundaries and only one is true at a time. Drawing `expiresAt` left
  // every trial in the table blank, which is the first thing anybody asks about a trial.
  test('every state shows the boundary that is true in it', async () => {
    for (const [state, chip] of [
      ['trial', 'Trial'],
      ['grace', 'In grace'],
      ['cancelled', 'Cancelled'],
    ] as const) {
      await page.goto(`/subscribers?state=${state}`)
      await expect(page.locator('tbody tr').first()).toBeVisible()
      const dates = await page.locator('tbody tr td:nth-child(4)').allTextContents()
      expect(dates.length).toBeGreaterThan(0)
      expect(dates, `${chip} rows should all carry a boundary`).not.toContain('—')
    }

    // The one place a dash belongs: expired without ever having paid, so there is no boundary
    // rather than one nobody filled in.
    await page.goto('/subscribers?state=expired')
    await expect(page.locator('tbody tr').first()).toBeVisible()
    const expired = await page.locator('tbody tr td:nth-child(4)').allTextContents()
    expect(expired.some((date) => date.trim() === '—')).toBe(true)
    expect(expired.some((date) => date.trim() !== '—')).toBe(true)
  })

  // The tooltip answers on the row, which is the only place somebody meeting this table has the
  // question. Reached by keyboard as well as by pointer: the native `title` this replaces never
  // appeared for anybody moving through a table with the keyboard.
  test('the state chip explains itself, to the keyboard as well', async () => {
    await page.goto('/subscribers?state=cancelled')
    await expect(page.locator('tbody tr').first()).toBeVisible()

    // The visible panel, not `getByRole('tooltip')`: Reka puts that role on a visually-hidden
    // span, so asserting on it alone would pass while the panel itself never appeared. Both are
    // checked, because the sentence has to reach an eye and a screen reader, and `toContainText`
    // rather than `toHaveText` because the panel holds the sentence twice — once for each.
    const panel = page.locator('[data-slot="tooltip-content"]')
    const announced = page.locator('[role="tooltip"]')

    await page.locator('tbody tr').first().getByText('Cancelled').hover()
    const cancelled = 'Access runs to the end of the paid period, then stops.'
    await expect(panel).toBeVisible()
    await expect(panel).toContainText(cancelled)
    await expect(announced).toHaveText(cancelled)

    // Focus, not hover. The native `title` this replaces never opened for anybody moving through
    // a table with the keyboard, which is half the reason it was replaced.
    await page.goto('/subscribers?state=grace')
    await expect(page.locator('tbody tr').first()).toBeVisible()
    await page.locator('tbody tr').first().getByText('In grace').focus()
    await expect(panel).toBeVisible()
    await expect(panel).toContainText('Paid period ended. Access extended as a courtesy.')
  })

  test('paging moves through the table and back', async () => {
    const firstName = await rows(page).first().locator('td').first().textContent()
    await page.getByRole('button', { name: 'Next' }).click()
    await expect(page).toHaveURL(/page=2/)
    await expect(rows(page).first().locator('td').first()).not.toHaveText(firstName ?? '')

    await page.getByRole('button', { name: 'Previous' }).click()
    await expect(page).toHaveURL(/\/subscribers$/)
  })

  test('an empty result says the filters caused it and offers to clear them', async () => {
    await page.getByLabel('Search').fill('zzzzz-nobody-has-this-name')
    await expect(page.getByText('No subscribers match these filters.')).toBeVisible()
    await page.getByRole('button', { name: 'Clear filters' }).last().click()
    await expect(rows(page)).toHaveCount(25)
  })

  // Typing must not fill the history with one entry per letter.
  test('typing a search leaves one step behind it, not one per letter', async () => {
    await page.getByLabel('Search').fill('a')
    await page.getByLabel('Search').fill('an')
    await page.getByLabel('Search').fill('ann')
    await expect(page).toHaveURL(/q=ann/)

    // One step back clears the whole search rather than one letter of it.
    await page.goBack()
    await expect(page).toHaveURL(/\/subscribers$/)
    await expect(page.getByLabel('Search')).toHaveValue('')
  })
})
