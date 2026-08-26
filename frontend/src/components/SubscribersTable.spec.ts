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
import { describe, expect, it } from 'vitest'
import { RouterLinkStub } from '@vue/test-utils'

import SubscribersTable from '@/components/SubscribersTable.vue'
import type { SubscriberSummary } from '@/domain/subscribers'

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
      sort: null,
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
    const table = render({ rows: [subscriber({ expiresAt: null, lastActiveAt: null })] })
    expect(table.findAll('td').at(3)?.text()).toBe('—')
    expect(table.findAll('td').at(4)?.text()).toBe('—')
  })

  it('survives a date the API should never send', () => {
    const table = render({ rows: [subscriber({ expiresAt: 'not a date' })] })
    expect(table.findAll('td').at(3)?.text()).toBe('—')
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
