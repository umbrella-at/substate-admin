/**
 * One page of the audit.
 *
 * Two things are worth a test here and the rest is markup. A row outlives the world it names — the
 * base world is rebuilt at every restart — so a link into a world that is gone answers 404 to
 * somebody who followed it in good faith. And the Result column is empty when the engine accepted
 * the call, because a column of "ok" down three hundred rows is three hundred words nobody reads
 * and the rows worth finding are the other ones.
 */

import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { AuditEntry } from '@/api/client'
import AuditTable from '@/components/AuditTable.vue'

function entry(over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'a-1',
    occurredAt: '2026-09-02T05:09:00Z',
    actor: { id: 'u-1', email: 'operator@example.com' },
    action: 'subscription.payment',
    targetType: 'subscription',
    targetId: 'sub-0001',
    worldId: 'base',
    outcome: 'ok',
    errorCode: null,
    payload: { amount: 500, provider: 'panel', reference: 'ref-1' },
    ...over,
  }
}

function render(rows: AuditEntry[], liveWorld: string | null = 'base') {
  return mount(AuditTable, {
    props: { rows, liveWorld },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

/** Collapsed, because a cell built from two elements carries the whitespace between them and the
 *  test would be asserting the template's line breaks. */
function cells(wrapper: ReturnType<typeof render>): string[] {
  return wrapper.findAll('tbody td').map((each) => each.text().replace(/\s+/gu, ' ').trim())
}

describe('the columns', () => {
  it('are the five this screen answers with, and no payload column', () => {
    const headers = render([entry()])
      .findAll('th')
      .map((each) => each.text())

    expect(headers).toEqual(['When', 'Who', 'Action', 'Subscriber', 'Result'])
  })

  it('carries the instant, the operator, what was asked and who it was about', () => {
    expect(cells(render([entry()]))).toEqual([
      '02 Sep 2026 05:09',
      'operator@example.com',
      'Recorded a payment · 5.00 · ref-1',
      'sub-0001',
      '',
    ])
  })
})

describe('the result', () => {
  // Nothing at all when it worked.
  it('says nothing about an accepted call', () => {
    expect(cells(render([entry()])).at(4)).toBe('')
  })

  it('names the code a refused call was given', () => {
    const refused = entry({ outcome: 'refused', errorCode: 'PROMO_ALREADY_BOUND' })

    expect(cells(render([refused])).at(4)).toBe('PROMO_ALREADY_BOUND')
  })
})

describe('a row that outlives its world', () => {
  it('links to the card when the row is about the world on screen', () => {
    const wrapper = render([entry()])

    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links).toHaveLength(1)
    expect(links[0]?.props('to')).toEqual({
      name: 'subscriber',
      params: { userId: 'sub-0001' },
    })
  })

  // A link into a world that no longer exists is a 404 for somebody who trusted it. The id stays
  // readable and becomes a filter instead.
  it('offers no link when the row belongs to another world', () => {
    const wrapper = render([entry({ worldId: 'a-sandbox' })])

    expect(wrapper.findAllComponents(RouterLinkStub)).toHaveLength(0)
    expect(wrapper.text()).toContain('sub-0001')
  })

  it('offers no link when there is no world at all', () => {
    const wrapper = render([entry()], null)

    expect(wrapper.findAllComponents(RouterLinkStub)).toHaveLength(0)
  })
})

describe('the identity cells', () => {
  // "Everything this operator did" and "everything done to this subscriber" are the two questions
  // this screen is opened with, and the row answers them.
  it('filters by the operator rather than navigating', async () => {
    const wrapper = render([entry()])

    await wrapper.findAll('button').at(0)?.trigger('click')

    expect(wrapper.emitted('filterActor')).toEqual([['u-1']])
  })

  it('filters by the subscriber when the row cannot be linked', async () => {
    const wrapper = render([entry({ worldId: 'a-sandbox' })])

    await wrapper.findAll('button').at(1)?.trigger('click')

    expect(wrapper.emitted('filterTarget')).toEqual([['sub-0001']])
  })
})
