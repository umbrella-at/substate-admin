/**
 * The table renders, and it renders the things that are hard to see missing.
 *
 * The first test is not ceremony. TanStack Table v9 builds its row model from the features that
 * are enabled, and a table configured with the wrong set type-checks perfectly and renders an
 * empty body — the columns are right, the header row is right, and there are simply no rows. That
 * failure looks exactly like "the API returned nothing", which is the one thing a table is
 * expected to do sometimes.
 */

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub } from '@vue/test-utils'

import SubscribersTable from '@/components/SubscribersTable.vue'
import { DEFAULT_SORT, type SubscriberSummary } from '@/domain/subscribers'

function subscriber(over: Partial<SubscriberSummary> = {}): SubscriberSummary {
  return {
    userId: 'u-1',
    displayName: 'Ada Lovelace',
    state: 'active',
    planId: 'monthly',
    expiresAt: '2026-09-01T00:00:00Z',
    lastActiveAt: '2026-08-20T00:00:00Z',
    ...over,
  }
}

function render(props: Partial<InstanceType<typeof SubscribersTable>['$props']> = {}) {
  return mount(SubscribersTable, {
    props: {
      rows: [subscriber()],
      sort: DEFAULT_SORT,
      sortHref: (field: string) => ({ query: { sort: field } }),
      busy: false,
      ...props,
    },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('the subscriber table', () => {
  it('puts one row on screen per subscriber', () => {
    const table = render({
      rows: [subscriber({ userId: 'u-1' }), subscriber({ userId: 'u-2', displayName: 'Grace' })],
    })
    expect(table.findAll('tbody tr')).toHaveLength(2)
    expect(table.text()).toContain('Ada Lovelace')
    expect(table.text()).toContain('Grace')
  })

  it('shows the identifier next to the name, because names repeat and identifiers do not', () => {
    expect(render().text()).toContain('u-1')
  })

  it('draws the state as its chip rather than its code', () => {
    expect(render({ rows: [subscriber({ state: 'grace' })] }).text()).toContain('In grace')
  })

  // An empty cell reads as a defect. A subscriber with no expiry is an ordinary thing.
  it('writes a dash where there is no date', () => {
    const table = render({ rows: [subscriber({ expiresAt: null })] })
    expect(table.findAll('td').at(3)?.text()).toBe('—')
  })

  it('survives a date the API should never send', () => {
    const table = render({ rows: [subscriber({ expiresAt: 'not a date' })] })
    expect(table.findAll('td').at(3)?.text()).toBe('—')
  })

  // Every day-first English locale writes September as "Sept" and everything else with three
  // letters, so one month in twelve breaks the alignment the fixed-width form exists for.
  it('gives every month the same width', () => {
    const table = render({
      rows: [
        subscriber({ userId: 'a', expiresAt: '2026-09-10T00:00:00Z' }),
        subscriber({ userId: 'b', expiresAt: '2026-10-04T00:00:00Z' }),
      ],
    })
    const dates = table.findAll('tbody tr').map((row) => row.findAll('td').at(3)?.text())
    expect(dates).toEqual(['10 Sep 2026', '04 Oct 2026'])
  })

  // Three of the five columns are quantities and offer an order from their header. The two
  // categories do not: an arrow is a direction over a magnitude, and neither a state nor a plan
  // is one.
  it('offers an order only from the columns that have one', () => {
    const table = render()
    const ordered = table.findAllComponents(RouterLinkStub)
    expect(ordered.length).toBe(3)
    expect(ordered.map((link) => link.text().replace(/\s+/gu, ' ').trim())).toEqual([
      'Subscriber',
      'Expires',
      'Last activity↓',
    ])
  })

  // The header still does something, and what it does is the thing the column is for.
  it('sends a category header to its filter instead', () => {
    const headers = render().findAll('th')
    expect(headers.at(1)?.find('a').attributes('href')).toBe('#filter-state')
    expect(headers.at(2)?.find('a').attributes('href')).toBe('#filter-plan')
  })

  // aria-sort says the table is ordered by this column. Plan can never be that column, and
  // saying "none" would claim it is a sortable one that happens to be unsorted.
  it('never announces a sort state for the column that can never have one', () => {
    expect(render().findAll('th').at(2)?.attributes('aria-sort')).toBeUndefined()
    expect(
      render({ sort: { field: 'state', descending: false } })
        .findAll('th')
        .at(2)
        ?.attributes('aria-sort'),
    ).toBeUndefined()
  })

  // State is not sorted from its header, but it can be the column the table is ordered by, and
  // aria-sort is a fact about the table rather than about where the control lives.
  it('announces the urgency order on the column it orders', () => {
    const headers = render({ sort: { field: 'state', descending: false } }).findAll('th')
    expect(headers.at(1)?.attributes('aria-sort')).toBe('ascending')
    expect(render().findAll('th').at(1)?.attributes('aria-sort')).toBeUndefined()
  })

  // Caught by looking rather than by any of the assertions above: a v-if placed between a
  // v-else-if and its v-else breaks the pair, and the orphaned v-else renders unconditionally.
  // Every header label was drawn twice and every test still passed, because the tests read the
  // link and the duplicate sits beside it.
  it('draws each header label once', () => {
    const table = render({ sort: { field: 'state', descending: false } })
    for (const [index, label] of ['Subscriber', 'State', 'Plan', 'Expires', 'Last activity'].entries()) {
      const text = table.findAll('th').at(index)?.text() ?? ''
      expect(text.split(label).length - 1).toBe(1)
    }
  })

  // And says it in words, because the vocabulary this column lacks is the arrow.
  it('names the order in the header rather than drawing it', () => {
    const header = render({ sort: { field: 'state', descending: false } }).findAll('th').at(1)
    expect(header?.text()).toContain('urgent first')
    expect(header?.text()).not.toMatch(/[↑↓]/u)
  })

  // The arrow is decoration; this is the part a screen reader announces.
  it('announces which column is sorted, and which way', () => {
    const table = render({ sort: { field: 'expiresAt', descending: true } })
    const headers = table.findAll('th')
    expect(headers.at(3)?.attributes('aria-sort')).toBe('descending')
    expect(headers.at(0)?.attributes('aria-sort')).toBe('none')
  })

  // The first screen carries no sort in its address and is still sorted, by the order the API
  // applies when asked for none. A header that drew nothing there would leave a real order with
  // nothing on screen to explain it.
  it('marks the default order on a table nobody has sorted yet', () => {
    const headers = render({ sort: DEFAULT_SORT }).findAll('th')
    expect(headers.at(4)?.attributes('aria-sort')).toBe('descending')
  })

  it('draws exactly one arrow', () => {
    const table = render({ sort: { field: 'expiresAt', descending: false } })
    expect(table.text().match(/[↑↓]/gu) ?? []).toHaveLength(1)
  })

  // Sorting by state is the API's urgency order, and it is offered by name elsewhere rather than
  // as an arrow here. The header must not start drawing one just because the sort is active.
  it('draws no arrow when the order is one it does not offer', () => {
    const table = render({ sort: { field: 'state', descending: false } })
    expect(table.text().match(/[↑↓]/gu) ?? []).toHaveLength(0)
  })

  it('says when it is waiting, without emptying itself', () => {
    const table = render({ busy: true })
    expect(table.get('table').attributes('aria-busy')).toBe('true')
    expect(table.findAll('tbody tr')).toHaveLength(1)
  })
})

/**
 * The activity column answers "recently or not", so it is read as words rather than as a date.
 *
 * The boundary cases are the whole point. `Intl.RelativeTimeFormat` with `numeric: 'auto'` renders
 * a count of zero as "this month" or "this year" — a phrase that would appear on a row eleven
 * months old if the bucket a value falls into and the unit it is divided by ever disagree. Every
 * bucket is therefore checked at its first instant, where the count must be exactly one.
 */
describe('how long ago', () => {
  const NOW = new Date('2026-08-26T12:00:00Z')

  const MINUTE = 60_000
  const HOUR = 60 * MINUTE
  const DAY = 24 * HOUR
  const MONTH = 30.436875 * DAY
  const YEAR = 12 * MONTH

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function activity(agoMs: number): string {
    const at = new Date(NOW.getTime() - agoMs).toISOString()
    const table = render({ rows: [subscriber({ lastActiveAt: at })] })
    return table.findAll('td').at(4)?.text() ?? ''
  }

  it.each([
    ['under a minute', 30 * 1000, 'just now'],
    ['one minute exactly', MINUTE, '1 minute ago'],
    ['fifty-nine minutes', 59 * MINUTE, '59 minutes ago'],
    ['one hour exactly', HOUR, '1 hour ago'],
    ['twenty-three hours', 23 * HOUR, '23 hours ago'],
    ['one day exactly', DAY, '1 day ago'],
    ['nine days', 9 * DAY, '9 days ago'],
    ['twenty-nine days', 29 * DAY, '29 days ago'],
    // The days bucket runs to the real length of a month rather than to a round number, so this
    // is the one case where thirty days is still counted in days.
    ['thirty days', 30 * DAY, '30 days ago'],
    ['one month exactly', MONTH, '1 month ago'],
    ['eleven months', 11 * MONTH, '11 months ago'],
    ['one year exactly', YEAR, '1 year ago'],
    ['three years', 3 * YEAR, '3 years ago'],
  ])('reads %s the way the series reads', (_name, ago, expected) => {
    expect(activity(ago)).toBe(expected)
  })

  // Anchored on the calendar rather than on this file's copy of the constants, which is what the
  // table above is: a scale built from a thirty-day month passes every one of those cases and
  // still reads 720 days as "2 years ago" for something one year and eleven months old. A phrase
  // ending in "ago" is a floor, and these are the values a floor must not round up.
  it.each([
    ['300 days', 300, '9 months ago'],
    ['364 days', 364, '11 months ago'],
    ['720 days', 720, '1 year ago'],
    ['1080 days', 1080, '2 years ago'],
    ['3600 days', 3600, '9 years ago'],
  ])('never rounds %s up to the next unit', (_name, days, expected) => {
    expect(activity(days * DAY)).toBe(expected)
  })

  // One series, read down a column. An idiom is a word that belongs to prose: "yesterday" between
  // "2 days ago" and "23 hours ago" is the row the eye stops on, and stopping is the cost. This is
  // an instrument, so every row is the same shape and only the number changes.
  it('never reaches for an idiom', () => {
    for (const ago of [DAY, 2 * DAY, MONTH, 2 * MONTH, YEAR, 2 * YEAR]) {
      expect(activity(ago)).toMatch(/^\d+ \w+ ago$/u)
    }
  })

  // The failure this shape of code produces is a count of zero. It used to surface as "this
  // month"; it would now surface as "0 months ago", which is no better and no less a bug.
  it('never counts zero of anything', () => {
    for (const ago of [MINUTE, HOUR, DAY, MONTH - 1, MONTH, YEAR - 1, YEAR, 2 * YEAR - 1]) {
      expect(activity(ago)).not.toMatch(/\b0 \w+ ago\b/u)
    }
  })

  // Somebody who has never turned up is a fact, not a missing value.
  it('says Never, quietly, for a subscriber who has not once turned up', () => {
    const table = render({ rows: [subscriber({ lastActiveAt: null })] })
    const cell = table.findAll('td').at(4)
    expect(cell?.text()).toBe('Never')
    expect(cell?.find('span').classes()).toContain('text-text-muted')
    expect(cell?.find('span').attributes('title')).toBeUndefined()
  })

  // The phrase is the answer; the timestamp is the evidence behind it.
  it('carries the exact moment on the hover, in ISO and in UTC', () => {
    const table = render({
      rows: [subscriber({ lastActiveAt: '2026-08-17T09:41:03.472Z' })],
    })
    expect(table.findAll('td').at(4)?.find('span').attributes('title')).toBe(
      '2026-08-17T09:41:03Z',
    )
  })

  it('does not claim a future timestamp is happening', () => {
    expect(activity(-5 * HOUR)).toBe('just now')
  })

  // A phrase, not a figure: monospace and a right edge would invite comparing these character by
  // character down the column, which is what the other date column is for.
  //
  // Asserted over the cell's whole rendered markup rather than over its class list. The `<td>`
  // carries one static class string shared by all five columns, so an assertion about it cannot
  // fail whatever this column renders — it would have looked like a check and been a decoration.
  // The markup covers the element the cell actually builds, and anything nested inside it.
  it('is ordinary left-aligned text', () => {
    const html = render().findAll('td').at(4)?.html() ?? ''
    expect(html).not.toMatch(/font-numeric|text-right|tabular-nums/u)
  })

  // A malformed timestamp is a defect somewhere behind this screen. It must not arrive as a
  // confident claim about a person's behaviour.
  it('does not call an unreadable timestamp Never', () => {
    const table = render({ rows: [subscriber({ lastActiveAt: 'not a timestamp' })] })
    expect(table.findAll('td').at(4)?.text()).toBe('—')
  })

  it('is named for what it records', () => {
    expect(render().findAll('th').at(4)?.text()).toContain('Last activity')
  })
})
