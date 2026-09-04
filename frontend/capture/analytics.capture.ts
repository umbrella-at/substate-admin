/**
 * The third picture: five figures, each with a question over it and a number under that. It
 * asserts what it photographed, for the reason the table's capture gives at length — a shot that
 * only waited for the page can quietly produce five skeletons.
 */

import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { account } from '../playwright.config.ts'

const SHOT = fileURLToPath(new URL('../../docs/analytics.png', import.meta.url))

/** Twelve months rather than the default ninety days. The two period figures then cover the whole
 *  of the world's history, which is what makes the flow line a shape rather than a segment. */
const QUERY = '?period=12m'

/** Taller than the table's shot, and the assertion below is what sets the number: five figures in
 *  three rows do not fit the height a table of twelve rows does, and a picture that cut the last
 *  plot in half would be a picture of four figures and a hint. */
test.use({ viewport: { width: 1440, height: 1380 } })

/** Every question on the screen, in the order it is drawn. A shot missing one is a shot of a
 *  screen that has lost a figure. */
const QUESTIONS = [
  'Who is arriving, and who is leaving?',
  'Where do we lose them?',
  'What is in the base right now?',
  'Who pays but has stopped turning up?',
  'How much money is coming in?',
]

test('the analytics screen', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  await page.goto(`/analytics${QUERY}`)

  for (const question of QUESTIONS) {
    await expect(page.getByRole('heading', { name: question, exact: true })).toBeVisible()
  }

  // Five canvases, and none of them still waiting. A skeleton on screen is a figure this picture
  // would show as a grey rectangle.
  await expect(page.locator('canvas')).toHaveCount(5)
  await expect(page.locator('.skeleton')).toHaveCount(0)

  // The five states, named as the chips name them, so the snapshot is a lifecycle rather than one
  // bar. Read off the list a screen reader gets, which carries the same numbers the plot draws.
  const states = page.getByText(/^(Trial|Active|In grace|Expired|Cancelled)$/)
  await expect(states).toHaveCount(5)

  // In the viewport rather than merely in the document: the screenshot is the window, so the last
  // plot has to be inside it and not merely the heading above it.
  await expect(page.locator('canvas').last()).toBeInViewport({ ratio: 1 })

  type Fonts = { document: { fonts: { ready: Promise<unknown> } } }
  await page.evaluate(() => (globalThis as unknown as Fonts).document.fonts.ready)

  // Chart.js animates on first paint, and `animations: 'disabled'` finishes a CSS transition
  // rather than a canvas one — so the figures are given their two hundred milliseconds first.
  await page.waitForTimeout(400)
  await page.screenshot({ path: SHOT, animations: 'disabled' })
})
