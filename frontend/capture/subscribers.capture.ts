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

import { expect, test } from '@playwright/test'

import { account } from '../playwright.config.ts'

/** Resolved from this file rather than from the working directory, which is whichever one the
 *  command that ran it was invoked from. */
const SHOT = fileURLToPath(new URL('../../docs/subscribers.png', import.meta.url))

/** Twelve rows rather than the default twenty-five: the pager is only worth showing next to the
 *  rows it pages through, and twenty-five of them push it a screen below the filters.
 *
 *  The order is the table's own, and the page is not the first one. Sorted by last activity, page
 *  one is everybody who turned up today — trials and actives, two colours for a column that has
 *  five. Further in, the same order holds four of them, and both pager buttons are live.
 *
 *  THE PAGE NUMBER IS RE-CHOSEN WHEN THE CALENDAR MOVES IT, and that is the arrangement rather
 *  than a maintenance cost. The seed fixes the population; the world is nine months of history
 *  ending now, so which people sit on which page of an activity-ordered table moves as the days
 *  do. It was page six; the assertion below is what said so rather than letting the picture
 *  quietly become a column of one colour. */
const QUERY = '?page=28&pageSize=12'
const PAGE_SIZE = 12

test('the subscriber table', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()

  // Signed in before navigating, not merely asked to be. The access token is held in memory and
  // the navigation below throws that heap away, so leaving early lands on the login page with a
  // refresh cookie that was never issued.
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  await page.goto(`/subscribers${QUERY}`)

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

  // Four kinds of chip at least, because a column of one colour says nothing about a lifecycle
  // and the five colours are most of what this screen has to explain.
  const distinct = new Set(await chips.allInnerTexts())
  expect(distinct.size).toBeGreaterThan(3)

  // The fonts are part of the design and arrive after the rows do; shooting before they land
  // photographs the fallback stack. `globalThis` because this file is type-checked without the
  // DOM lib, the same way the table scenario reaches `scrollY`.
  type Fonts = { document: { fonts: { ready: Promise<unknown> } } }
  await page.evaluate(() => (globalThis as unknown as Fonts).document.fonts.ready)

  // `animations: 'disabled'` is what makes two runs comparable: it finishes CSS transitions
  // rather than catching one of them a third of the way through.
  await page.screenshot({ path: SHOT, animations: 'disabled' })
})
