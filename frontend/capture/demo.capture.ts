/**
 * The gif in the README: a stranger presses one button, gets a world, and moves it.
 */

/* WHAT IT HAS TO SHOW IN ONE FRAME is the table AND the thing that changed it: a tour of screens
   would say nothing three screenshots have not already said. */

/* IT ASSERTS WHAT IT RECORDED. A gif in which no chip changed colour is a failed run rather than
   a dull picture: the whole claim is that time passing moves subscriptions between states, and a
   recording that does not show it is a recording of something else. */

/* The world is a SANDBOX, opened through the demonstration door. Winding the base world would
   move the world the screenshots beside this one are taken from. */

import { fileURLToPath } from 'node:url'
import { readFileSync, writeFileSync } from 'node:fs'

import { expect, test, type Locator, type Page } from '@playwright/test'

import { distanceTo, encodeGif, paletteIn, type Frame } from './gif.ts'

const GIF = fileURLToPath(new URL('../../docs/demo.gif', import.meta.url))
const TOKENS = fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url))

/** How far a chip's colour may sit from the nearest thing the palette can draw. */

/* Measured against the failure it exists to catch: quantized from the sign-in screen alone, the
   five chip colours landed 22 to 118 away from anything in the palette — all of them blue-grey. */
const NEAREST = 12

/** Six rows: enough chips to see several change, few enough that the pager, the table and the
 *  clock are all in one frame at this height. */

/* Measured: of ten visible rows, five changed state under the first press of a month, two under
   the second, three under the third — so six is two or three moving rather than a hopeful one. */
const PAGE_SIZE = 6

/** By name, ascending. The world goes on living while it is wound, so the people on page one are
 *  not quite the same set afterwards — but a name is a stable key where "last active" is not, and
 *  a page re-sorted under every press would show motion that is not the subject. */
const SORT = 'displayName'

/** How many months to press, as a range rather than a number. */

/* WRITTEN DOWN, IT IS A COIN: how far the world has to move before the six on screen are
   somewhere else is a property of the calendar the run lands on. */

/* Measured over one world: one press moved one of them, two moved two, and three moved none at
   all — the states had cycled back. */

/* So the run presses until the picture shows what it claims, and fails if it never does. Two at
   least, because one press is a coincidence and two is a world running. */
const PRESSES = { least: 2, most: 6 }

/** Milliseconds. Long enough on the frames somebody reads, short on the ones that are a press
 *  happening — a gif nobody can follow is a gif of the wrong thing. */
const BEAT = { read: 1300, react: 220, land: 900, last: 2600 }

test.use({ viewport: { width: 1280, height: 920 }, deviceScaleFactor: 1 })

/**
 * THE CROP, AND IT IS THE ARGUMENT OF THE WHOLE PICTURE. One frame has to hold the clock — which
 * is what moves the world — and the state column, which is what moving it changes.
 */

/* Declared rather than measured, which is the one place this file departs from decision 239: the
   login frames are taken before a table exists, and every frame of a gif is one size. */

/* What measurement does instead is refuse. The run asserts the clock, the state column, the date
   and the count are all inside this rectangle, so a layout that outgrows it fails here. */
const FRAME = { x: 0, y: 0, width: 1100, height: 900 }

test('the demonstration, wound forward', async ({ page }) => {
  const frames: Frame[] = []
  const opened = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/demo/session',
  )

  await page.goto('/login')
  await settle(page)

  // The button a stranger presses, and the world it hands back.
  const door = page.getByRole('button', { name: 'Try the demo', exact: true })
  await expect(door).toBeVisible()
  frames.push(await shot(page, FRAME, BEAT.read), await shot(page, FRAME, BEAT.read))

  await door.click()
  frames.push(await shot(page, FRAME, BEAT.react))
  expect((await opened).status(), 'the demonstration door must open a world').toBe(200)
  await expect(page.getByRole('link', { name: 'Subscribers' })).toBeVisible()

  await page.goto(`/subscribers?pageSize=${PAGE_SIZE}&sort=${SORT}`)
  await expect(rows(page)).toHaveCount(PAGE_SIZE)
  await settle(page)

  await bothInFrame(page)

  frames.push(await shot(page, FRAME, BEAT.read), await shot(page, FRAME, BEAT.read))

  const month = page.getByRole('button', { name: 'Month', exact: true })
  /** The states in the frame the animation opens the table on, kept for the end. */
  const opening = await states(page)
  let moved = 0
  let after = opening

  for (let press = 0; press < PRESSES.most; press += 1) {
    const before = await states(page)

    // BOTH ANSWERS, NOT JUST THE CLOCK'S. The advance invalidates every other query and the table
    // refetches after it; waiting on the clock alone reads the rows that are still on screen —
    // which is how the first version of this compared a frame with itself and found no movement.
    const wound = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/clock/advance' && response.status() === 200,
    )
    const listed = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/subscribers' && response.status() === 200,
    )
    await month.click()
    // Mid-press: the label has changed and the table is dimmed behind it. Two beats, because one
    // frame of a transition reads as a glitch rather than as a wait.
    frames.push(await shot(page, FRAME, BEAT.react), await shot(page, FRAME, BEAT.react))
    await wound
    await listed
    await expect(rows(page)).toHaveCount(PAGE_SIZE)
    await settle(page)

    after = await states(page)
    moved += [...before].filter(([who, was]) => after.has(who) && after.get(who) !== was).length

    // Enough when the frame a reader rests on differs from the frame they started at.
    const ended = [...opening].filter(([who, was]) => after.has(who) && after.get(who) !== was)
    const last = ended.length > 0 && press + 1 >= PRESSES.least

    frames.push(await shot(page, FRAME, last ? BEAT.last : BEAT.land))
    if (!last) frames.push(await shot(page, FRAME, BEAT.land))
    if (last) break
  }

  // THE ASSERTION THIS FILE EXISTS FOR. Same person, different state, under a press, in a picture
  // that claims exactly that. Compared by subscriber rather than by row, because the rows move.
  expect(
    moved,
    `no subscriber changed state under any of ${PRESSES.most} presses, so this gif shows nothing`,
  ).toBeGreaterThan(0)

  // AND THE FRAME A READER RESTS ON DIFFERS FROM THE ONE THEY STARTED AT. Counting per-press
  // transitions alone is satisfied by a subscriber that leaves a state and comes back to it, and
  // the last frame is then identical to the first — which is what the first version of this shipped.
  const ended = [...opening].filter(([who, was]) => after.has(who) && after.get(who) !== was)
  expect(
    ended.length,
    `after ${PRESSES.most} presses the last frame still holds the states of the first, so the ` +
      'picture shows no movement',
  ).toBeGreaterThan(0)

  // And the clock itself said so, which is the other half of the frame.
  await expect(page.getByText(/\d+ days ahead of today/u)).toBeVisible()

  // The chips' own colours are reserved in the palette rather than hoped for: a chip is a few
  // hundred pixels of a million, and quantizing merges it into the greys around it.
  const chips = chipColours()
  const gif = encodeGif(
    frames,
    chips.map(([, hex]) => hex),
  )

  // FIVE CHIPS HAVE TO STILL BE FIVE COLOURS. A gif carries 256 colours for the whole animation,
  // and a palette that cannot draw green or amber turns the subject of this picture into greys.
  const palette = paletteIn(gif)
  for (const [name, hex] of chips) {
    expect(distanceTo(palette, hex), `${name} (${hex}) is not in the gif's palette`).toBeLessThan(
      NEAREST,
    )
  }

  writeFileSync(GIF, gif)
})

/** The ten state colours — five fills and the five texts on them — read from the stylesheet that
 *  declares them rather than copied here. */
function chipColours(): [string, string][] {
  const css = readFileSync(TOKENS, 'utf8')
  const found = [...css.matchAll(/--color-(state-[a-z]+-(?:bg|text)):\s*(#[0-9a-f]{6})/gu)]
  expect(found.length, 'five state chips, a fill and a text each, declared in tokens.css').toBe(10)
  return found.map((match) => [match[1]!, match[2]!])
}

function rows(page: Page): Locator {
  return page.locator('tbody tr')
}

/** Who is on the page and what state they are in, keyed by the identifier in their link. */

/* The State column is found by its heading rather than by a position: read at a fixed index, a
   column inserted before it turns this into a record of everybody's display name. */
async function states(page: Page): Promise<Map<string, string>> {
  const headings = await page.locator('thead th').allInnerTexts()
  const column = headings.findIndex((heading) => heading.trim() === 'State')
  expect(column, 'the table has no State column').toBeGreaterThanOrEqual(0)

  const found = new Map<string, string>()
  for (const row of await rows(page).all()) {
    const href = await row.locator('a[href^="/subscribers/"]').first().getAttribute('href')
    const state = await row.locator('td').nth(column).innerText()
    if (href !== null) found.set(href, state.trim())
  }
  expect(found.size, 'no row carried a subscriber link').toBeGreaterThan(0)
  return found
}

/**
 * Refuse a layout that has outgrown the frame.
 */

/* What the picture claims to hold, asked of the page rather than assumed. A column added to the
   table pushes one of them out of frame, and this is the only thing that would notice. */
async function bothInFrame(page: Page): Promise<void> {
  const parts = {
    'the clock, which is what moves the world': page.getByRole('region', { name: 'World clock' }),
    'the state column, where a chip is seen changing': page
      .locator('thead th')
      .filter({ hasText: 'State' })
      .first(),
    'the plan beside it, so the chip is not at the edge of the frame': page
      .locator('thead th')
      .filter({ hasText: 'Plan' })
      .first(),
    'the access date, which moves with the world': page
      .locator('thead th')
      .filter({ hasText: 'Access until' })
      .first(),
    'the count, which says how many people the world holds': page.getByText(/\d+ subscribers/),
  }

  for (const [what, locator] of Object.entries(parts)) {
    const box = await locator.boundingBox()
    expect(box, `${what} is not on screen at all`).not.toBeNull()
    expect(box!.x + box!.width, `${what} is off the right of the frame`).toBeLessThanOrEqual(
      FRAME.width,
    )
    expect(box!.y + box!.height, `${what} is below the frame`).toBeLessThanOrEqual(FRAME.height)
  }
}

/** One frame, and how long it holds. */
async function shot(
  page: Page,
  clip: { x: number; y: number; width: number; height: number },
  ms: number,
): Promise<Frame> {
  return { png: await page.screenshot({ clip, animations: 'disabled' }), ms }
}

/** The fonts are part of the design and arrive after the markup does; a frame taken before they
 *  land is a frame of the fallback stack, and one frame of it in the middle is a flicker. */
async function settle(page: Page): Promise<void> {
  type Fonts = { document: { fonts: { ready: Promise<unknown> } } }
  await page.evaluate(() => (globalThis as unknown as Fonts).document.fonts.ready)
}
