/**
 * The picture at the top of the README: the subscriber table, as it is.
 *
 * WHAT IS DETERMINISTIC HERE, AND WHAT IS NOT. The world is built from one seed, so the same
 * people are in it in the same order every time and two runs against one world give the same PNG
 * byte for byte. What the seed does not fix is the calendar: the world is nine months of history
 * ending now, so it is rebuilt around whatever day it is run, and a re-shoot months later moves
 * the dates and can move a row between states. That is when the assertions below earn their
 * keep — they fail rather than let the picture quietly get worse.
 *
 * IT ASSERTS WHAT IT PHOTOGRAPHED. A capture that only waits for the page can quietly produce a
 * dull or broken picture — one state chip repeated down the column, a pager that is not there, a
 * table still loading. Each of those is a failed run here, because the alternative is finding out
 * from the README.
 */

import { fileURLToPath } from 'node:url'

import { expect, test, type Page } from '@playwright/test'

import { account } from '../playwright.config.ts'

/** Resolved from this file rather than from the working directory, which is whichever one the
 *  command that ran it was invoked from. */
const SHOT = fileURLToPath(new URL('../../docs/subscribers.png', import.meta.url))

/** Twelve rows rather than the default twenty-five: the pager is only worth showing next to the
 *  rows it pages through, and twenty-five of them push it a screen below the filters. */
const PAGE_SIZE = 12

/** THE PAGE IS CHOSEN HERE RATHER THAN WRITTEN DOWN, and that is the correction.
 *
 *  A pinned number was re-chosen by hand every time the calendar moved under the world — it was
 *  six, then twenty-eight — and measuring it finally said why that never stopped: over 21 landing
 *  days the states on page 28 ran 2 to 4, and no page at all reached four on 8 of those days. A
 *  written-down page with a floor under it is a coin, and it came up tails in CI.
 *
 *  So the run asks the table which page has the most of the lifecycle on it and photographs that
 *  one. The floor below is what the world always affords: three of the five, on all 21 days. */
const COLOURS = 3

/** The table's own order, which is what makes the picture honest and also what caps it. Activity
 *  and state are correlated by construction — today's visitors are trials and actives, the long
 *  silent are expired and cancelled — so a page of twelve spans three states, not five. */
const SORT = '-lastActiveAt'

test('the subscriber table', async ({ page }) => {
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/auth/login' &&
      response.request().method() === 'POST',
  )

  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()

  // Signed in before navigating, not merely asked to be. The access token is held in memory and
  // the navigation below throws that heap away, so leaving early lands on the login page with a
  // refresh cookie that was never issued.
  const { accessToken } = (await (await login).json()) as { accessToken: string }
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  const chosen = await richestPage(page, accessToken)
  await page.goto(`/subscribers?page=${chosen}&pageSize=${PAGE_SIZE}&sort=${SORT}`)

  const rows = page.locator('tbody tr')
  await expect(rows).toHaveCount(PAGE_SIZE)

  // The three things the shot is for. A screenshot missing any of them is a screenshot of a
  // different screen.
  const chips = rows.getByText(/^(Trial|Active|In grace|Expired|Cancelled)$/)
  await expect(chips).toHaveCount(PAGE_SIZE)
  await expect(page.getByRole('group', { name: 'State' })).toBeVisible()

  // In the viewport, not merely in the document: the screenshot is the window, so a pager that
  // has scrolled below it is a pager the picture does not have.
  await expect(page.getByRole('button', { name: 'Next' })).toBeInViewport({ ratio: 1 })

  // Enough of the lifecycle to explain the colours. A column of one says nothing about it.
  const distinct = new Set(await chips.allInnerTexts())
  expect(distinct.size).toBeGreaterThanOrEqual(COLOURS)

  // The fonts are part of the design and arrive after the rows do; shooting before they land
  // photographs the fallback stack. `globalThis` because this file is type-checked without the
  // DOM lib, the same way the table scenario reaches `scrollY`.
  type Fonts = { document: { fonts: { ready: Promise<unknown> } } }
  await page.evaluate(() => (globalThis as unknown as Fonts).document.fonts.ready)

  // `animations: 'disabled'` is what makes two runs comparable: it finishes CSS transitions
  // rather than catching one of them a third of the way through.
  await page.screenshot({ path: SHOT, animations: 'disabled' })
})

/**
 * The page of twelve holding the most states, asked of the table rather than assumed. Read whole
 * rather than page by page: four requests instead of thirty, and the order is the one the browser
 * is about to ask for.
 */
async function richestPage(page: Page, accessToken: string): Promise<number> {
  const states: string[] = []
  for (const chunk of [1, 2, 3, 4]) {
    const answer = await page.request.get(
      `/api/subscribers?page=${chunk}&pageSize=100&sort=${SORT}`,
      { headers: { authorization: `Bearer ${accessToken}` } },
    )
    const body = (await answer.json()) as { items: { state: string }[] }
    states.push(...body.items.map((item) => item.state))
  }

  let best = { page: 1, distinct: 0 }
  // The last page is skipped: a short page draws a pager with nothing after it.
  for (let start = 0; start + 2 * PAGE_SIZE <= states.length; start += PAGE_SIZE) {
    const distinct = new Set(states.slice(start, start + PAGE_SIZE)).size
    if (distinct > best.distinct && start > 0) best = { page: start / PAGE_SIZE + 1, distinct }
  }
  expect(
    best.distinct,
    'no page of the table held enough of the lifecycle to photograph',
  ).toBeGreaterThanOrEqual(COLOURS)
  return best.page
}
