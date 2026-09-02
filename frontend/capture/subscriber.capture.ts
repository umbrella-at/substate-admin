/**
 * The second picture in the README: one subscriber's card, with what can be done to them.
 *
 * WHY A SECOND SHOT RATHER THAN A WIDER ONE. The table's picture answers "what does this panel
 * hold"; this one answers "what does it let you do", and those are the two questions somebody
 * opening the repository has. A single screenshot would have to be one or the other.
 *
 * NO SUBSCRIBER IS NAMED HERE. The world is built from one seed, so the population is the same
 * every run — but it is nine months of history ending now, and the ticker crosses boundaries every
 * thirty seconds, so which person is in which state moves under a re-shoot. The subject is chosen
 * from a filtered table, which is a question the world always answers and always with somebody.
 *
 * IT ASSERTS WHAT IT PHOTOGRAPHED, for the reason the table's capture records: a shot that only
 * waits for the page can produce a card still loading, an empty history, or an operations panel
 * that failed to draw, and the alternative to failing here is finding out from the README.
 */

import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { account } from '../playwright.config.ts'

const SHOT = fileURLToPath(new URL('../../docs/subscriber.png', import.meta.url))

/** GRACE is the state the panel is most about: a paying customer whose payment did not arrive, the
 *  one state with two distinct boundaries, and the one `docs/design.md` says to call today. It is
 *  also the smallest population — a handful out of three hundred and fifty — so the shot proves
 *  the filter finds them. */
const STATE = 'grace'

test('a subscriber card', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()

  // Signed in before navigating, not merely asked to be: the access token is held in memory and
  // the navigation below throws that heap away.
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  await page.goto(`/subscribers?state=${STATE}`)
  const first = page.locator('tbody tr').first()
  await expect(first).toBeVisible()
  await first.getByRole('link').click()

  // The two boundaries this state owns, which is the whole argument of the card's layout: the
  // payment that was missed, and the day access stops.
  await expect(page.getByText('Paid period ended', { exact: true })).toBeVisible()
  await expect(page.getByText('Grace ends', { exact: true })).toBeVisible()
  // And the three it does not.
  await expect(page.getByText('Trial ends', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Cancelled', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Access ended', { exact: true })).toHaveCount(0)

  // Every operation this state offers, enumerated. A picture of a panel missing one of them is a
  // picture of a different panel.
  const operations = page.locator('h3')
  await expect(operations).toHaveText([
    'Record a payment',
    'Change plan',
    'Redeem a promo code',
    'Assign a referral programme',
    'Cancel subscription',
  ])

  // A history with something in it. An empty feed under a card is the one thing this shot must
  // not show, because it is what a broken journal looks like.
  const feed = page.locator('table').last().locator('tbody tr')
  await expect(feed.first()).toBeVisible()

  // In the viewport rather than merely in the document: the screenshot is the window.
  await expect(page.getByRole('button', { name: 'Record a payment' })).toBeInViewport({ ratio: 1 })

  type Fonts = { document: { fonts: { ready: Promise<unknown> } } }
  await page.evaluate(() => (globalThis as unknown as Fonts).document.fonts.ready)

  await page.screenshot({ path: SHOT, animations: 'disabled' })
})
