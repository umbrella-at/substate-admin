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

  it('makes every sortable header a link, so the order can be opened in a new tab', () => {
    const links = render().findAllComponents(RouterLinkStub)
    expect(links.length).toBe(5)
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
    const table = render({ sort: { field: 'state', descending: false } })
    expect(table.text().match(/[↑↓]/gu) ?? []).toHaveLength(1)
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
  const MONTH = 30 * DAY
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
    ['one day exactly', DAY, 'yesterday'],
    ['nine days', 9 * DAY, '9 days ago'],
    ['twenty-nine days', 29 * DAY, '29 days ago'],
    ['one month exactly', MONTH, 'last month'],
    ['eleven months', 11 * MONTH, '11 months ago'],
    ['one year exactly', YEAR, 'last year'],
    ['three years', 3 * YEAR, '3 years ago'],
  ])('reads %s as "%s"', (_name, ago, expected) => {
    expect(activity(ago)).toBe(expected)
  })

  // The failure this shape of code produces: a count of zero, which `numeric: 'auto'` turns into
  // a phrase that sounds current.
  it('never says today, this month or this year', () => {
    for (const ago of [MONTH - 1, MONTH, YEAR - 1, YEAR, 2 * YEAR - 1]) {
      expect(activity(ago)).not.toMatch(/^(today|this month|this year|now)$/u)
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
  it('is ordinary left-aligned text', () => {
    const table = render()
    const cell = table.findAll('td').at(4)
    expect(cell?.classes().join(' ')).not.toMatch(/font-numeric|text-right/u)
    expect(cell?.find('span').classes().join(' ')).not.toMatch(/font-numeric|text-right/u)
  })

  it('is named for what it records', () => {
    expect(render().findAll('th').at(4)?.text()).toContain('Last activity')
  })
})
