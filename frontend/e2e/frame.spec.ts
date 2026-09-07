/**
 * The floor docs/design.md promises and nothing checked: responsive down to a phone.
 */

/* A table is allowed to scroll sideways inside its own container. The PAGE is not: when the frame
   itself overflows, the heading, the filters and the navigation all leave the screen with it. */

/* Asserted with the clock control drawn, because it is the widest thing in the sidebar — three
   step buttons that do not wrap — and it is the reason the frame broke here before. */

import { expect, test } from '@playwright/test'

import { account } from '../playwright.config.ts'

/** The narrowest phone still worth supporting, and the width the design file's floor names. */
test.use({ viewport: { width: 375, height: 800 } })

test('the frame fits a phone, on every screen that has one', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email', { exact: true }).fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  // The control that makes the sidebar as wide as it ever gets.
  await expect(page.getByRole('region', { name: 'World clock' })).toBeVisible()

  // Walked through the navigation rather than reloaded five times: it is how somebody moves
  // around the panel, and a reload each is five bootstraps this assertion does not need.
  for (const section of ['Dashboard', 'Subscribers', 'Analytics', 'Audit', 'Users and roles']) {
    const link = page.getByRole('link', { name: section, exact: true })
    await link.click()
    // Arrived, said by the frame itself: the guard marks the entry for the page being looked at.
    await expect(link).toHaveAttribute('aria-current', 'page')

    // `globalThis` because this file is type-checked without the DOM lib, the same way the
    // capture scripts reach `document.fonts`.
    type Page = { document: { documentElement: { scrollWidth: number } }; innerWidth: number }
    const overflow = await page.evaluate(() => {
      const scope = globalThis as unknown as Page
      return scope.document.documentElement.scrollWidth - scope.innerWidth
    })
    expect(overflow, `${section} scrolls sideways by ${overflow}px at 375`).toBeLessThanOrEqual(0)
  }
})
