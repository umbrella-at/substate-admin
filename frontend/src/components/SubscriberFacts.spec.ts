/**
 * What the card says about a subscriber, and what it deliberately does not.
 *
 * The rows are enumerated per state rather than probed. That is the whole difference between this
 * design and a card with three fixed date rows: with fixed rows every state renders the same three
 * labels, so an ACTIVE card that put a grace date in the third one passes every check that asks
 * whether the right row is present. Enumeration is the only assertion that can fail on a row that
 * should not be there.
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { PlanSummary, SubscriberDetail } from '@/api/client'
import SubscriberFacts from '@/components/SubscriberFacts.vue'

const MONTHLY: PlanSummary = {
  id: 'monthly',
  price: 500,
  currency: 'USD',
  periodUnit: 'months',
  periodCount: 1,
  trialDays: 14,
  graceDays: 5,
}

function detail(over: Partial<SubscriberDetail['subscriber']> = {}, rest = {}): SubscriberDetail {
  return {
    subscriber: {
      userId: 'sub-0001',
      displayName: 'Ada Lovelace',
      state: 'active',
      planId: 'monthly',
      accessUntil: '2026-10-16T00:00:00Z',
      expiresAt: '2026-10-16T00:00:00Z',
      trialEndsAt: null,
      graceEndsAt: null,
      cancelledAt: null,
      pendingPlanId: null,
      lastActiveAt: null,
      promoCode: null,
      referrerId: null,
      ...over,
    },
    plan: MONTHLY,
    promoCode: null,
    referrerId: null,
    referrerProgramId: null,
    referralProgramId: null,
    trialStartedAt: null,
    ...rest,
  }
}

function render(card: SubscriberDetail) {
  return mount(SubscriberFacts, {
    props: { detail: card },
    global: { stubs: { StateChip: { template: '<span>{{ state }}</span>', props: ['state'] } } },
  })
}

/** Every label on the card, in the order it is drawn. */
function labels(wrapper: ReturnType<typeof render>): string[] {
  return wrapper.findAll('dt').map((each) => each.text())
}

function valueOf(wrapper: ReturnType<typeof render>, label: string): string {
  const index = labels(wrapper).indexOf(label)
  return wrapper.findAll('dd').at(index)?.text() ?? ''
}

const CONSTANT = [
  'Plan',
  'Price',
  'Promo code',
  'Referred by',
  'Referral programme',
  'Last activity',
]

describe('the rows a state has', () => {
  // One boundary row in four states, two in grace and in cancelled, and never a row for a
  // boundary the state does not have.
  it.each([
    ['trial', { state: 'trial' as const, trialEndsAt: '2026-09-16T00:00:00Z' }, ['Trial ends']],
    ['active', { state: 'active' as const }, ['Expires']],
    [
      'grace',
      { state: 'grace' as const, graceEndsAt: '2026-10-21T00:00:00Z' },
      ['Paid period ended', 'Grace ends'],
    ],
    [
      'cancelled',
      { state: 'cancelled' as const, cancelledAt: '2026-09-02T00:00:00Z' },
      ['Cancelled', 'Access ends'],
    ],
    ['expired', { state: 'expired' as const }, ['Access ended']],
  ])('draws exactly the boundaries %s owns', (_name, over, boundaries) => {
    const wrapper = render(detail(over))

    expect(labels(wrapper)).toEqual([...boundaries, ...CONSTANT])
  })

  // The one em dash on a boundary, and it is the same one the table draws for the same fact.
  it('draws a dash for an expiry that never existed', () => {
    const wrapper = render(detail({ state: 'expired', expiresAt: null, accessUntil: null }))

    expect(valueOf(wrapper, 'Access ended')).toBe('—')
  })

  // A pending plan is not a boundary and not always there, so it gets a row only when it exists.
  it('names the next plan only when one is waiting', () => {
    expect(labels(render(detail({ pendingPlanId: 'annual' })))).toContain('Next plan')
    expect(labels(render(detail()))).not.toContain('Next plan')
  })
})

describe('a value that is not there', () => {
  // These are relations the subscriber does not have, not questions the state cannot be asked, so
  // their rows stay and say `—`. Two absences, two marks.
  it.each(['Promo code', 'Referred by', 'Referral programme'])(
    'keeps the %s row and dashes it',
    (label) => {
      const wrapper = render(detail())

      expect(labels(wrapper)).toContain(label)
      expect(valueOf(wrapper, label)).toBe('—')
    },
  )

  it('says Never rather than a dash for somebody who has not turned up', () => {
    expect(valueOf(render(detail({ lastActiveAt: null })), 'Last activity')).toBe('Never')
  })
})

describe('the facts beside the dates', () => {
  it('writes a monthly plan as every month rather than every 1 months', () => {
    expect(valueOf(render(detail()), 'Price')).toBe('5.00 USD every month')
  })

  it('writes a longer period with its count', () => {
    const wrapper = render(detail({}, { plan: { ...MONTHLY, id: 'quarterly', periodCount: 3 } }))

    expect(valueOf(wrapper, 'Price')).toBe('5.00 USD every 3 months')
  })

  // The one duration on the card. The question is whether this person has been seen lately, and a
  // date makes the reader do the subtraction — which is the argument the table's column already won.
  it('says how long ago somebody was last seen', () => {
    const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString()

    expect(valueOf(render(detail({ lastActiveAt: hourAgo })), 'Last activity')).toBe('1 hour ago')
  })

  // Two facts about two different people, and the field names used to disagree about which.
  it('keeps the referrer and their programme in the referrer row', () => {
    const wrapper = render(
      detail(
        {},
        { referrerId: 'sub-0009', referrerProgramId: 'partners', referralProgramId: 'users' },
      ),
    )

    expect(valueOf(wrapper, 'Referred by')).toContain('sub-0009')
    expect(valueOf(wrapper, 'Referred by')).toContain('partners')
    expect(valueOf(wrapper, 'Referral programme')).toBe('users')
  })
})

describe('a row that contradicts itself', () => {
  // Not an empty card. The state claims a date it always has and the row arrived without it, which
  // means the panel and the service disagree — and a card that silently omits them reads as a
  // subscriber with no dates.
  it('says so rather than drawing nothing', () => {
    const wrapper = render(detail({ state: 'active', expiresAt: null }))

    expect(wrapper.findAll('dt')).toHaveLength(0)
    expect(wrapper.text()).toContain("This subscription's dates could not be read.")
  })
})
