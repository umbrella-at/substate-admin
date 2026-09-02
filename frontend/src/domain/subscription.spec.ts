/**
 * The narrowing the card's whole layout rests on.
 *
 * `schema.d.ts` types every boundary as `string | null` on every state, and the backend's nulling
 * of the ones a state does not own is a runtime invariant `vue-tsc` cannot see. This is where that
 * invariant is checked: the arms carry what their state has and nothing else, and the row list is
 * asserted by enumeration rather than by looking for the row somebody was thinking about — a
 * `toContain` cannot fail when an extra row appears beside the right one.
 */

import { describe, expect, it } from 'vitest'

import type { SubscriberSummary } from '@/domain/subscribers'
import {
  boundaries,
  boundaryRows,
  canStartNewSubscription,
  paymentWouldApply,
} from '@/domain/subscription'

const TRIAL_ENDS = '2026-09-14T00:00:00Z'
const EXPIRES = '2026-10-02T00:00:00Z'
const GRACE_ENDS = '2026-10-07T00:00:00Z'
const CANCELLED_AT = '2026-08-12T00:00:00Z'

function row(over: Partial<SubscriberSummary> = {}): SubscriberSummary {
  return {
    userId: 'sub-0001',
    displayName: 'Ada Lovelace',
    state: 'active',
    planId: 'monthly',
    accessUntil: EXPIRES,
    expiresAt: EXPIRES,
    lastActiveAt: null,
    ...over,
  }
}

describe('the dates a state actually has', () => {
  it('gives a trial its trial boundary and nothing else', () => {
    const dates = boundaries(row({ state: 'trial', trialEndsAt: TRIAL_ENDS, expiresAt: null }))

    expect(dates).toEqual({ state: 'trial', trialEndsAt: TRIAL_ENDS })
  })

  it('gives an active subscription its expiry and nothing else', () => {
    expect(boundaries(row({ state: 'active' }))).toEqual({ state: 'active', expiresAt: EXPIRES })
  })

  // The one state with two distinct dates, and the one an operator is looking at when they open
  // this card: the payment that was missed, and the day access stops.
  it('gives a grace period both of its dates', () => {
    const dates = boundaries(row({ state: 'grace', graceEndsAt: GRACE_ENDS }))

    expect(dates).toEqual({ state: 'grace', expiresAt: EXPIRES, graceEndsAt: GRACE_ENDS })
  })

  it('gives a cancelled subscription the day it was cancelled and the day it stops', () => {
    const dates = boundaries(row({ state: 'cancelled', cancelledAt: CANCELLED_AT }))

    expect(dates).toEqual({ state: 'cancelled', cancelledAt: CANCELLED_AT, expiresAt: EXPIRES })
  })

  // The one absence the type admits, and it is the one the table already draws an em dash for:
  // a subscription that ended without a payment ever being made.
  it('lets an expired subscription have no expiry at all', () => {
    expect(boundaries(row({ state: 'expired', expiresAt: null }))).toEqual({
      state: 'expired',
      expiresAt: null,
    })
  })

  // Not an empty card. A state that claims a date it always has, arriving without it, means the
  // panel and the service disagree — and inventing a shape for it is how the impossible state
  // becomes representable one layer further in.
  it.each([
    ['trial', row({ state: 'trial', trialEndsAt: null })],
    ['active', row({ state: 'active', expiresAt: null })],
    ['grace', row({ state: 'grace', graceEndsAt: null })],
    ['grace without an expiry', row({ state: 'grace', expiresAt: null, graceEndsAt: GRACE_ENDS })],
    ['cancelled', row({ state: 'cancelled', cancelledAt: null })],
  ])('refuses to describe a %s row that contradicts itself', (_name, given) => {
    expect(boundaries(given)).toBeNull()
  })
})

describe('the rows the card draws', () => {
  // Enumerated, not probed: the point of hiding rows is that the ones on screen are all of them,
  // and an assertion that the wanted row is present cannot fail when a wrong one is beside it.
  it.each([
    ['trial', row({ state: 'trial', trialEndsAt: TRIAL_ENDS }), ['Trial ends']],
    ['active', row({ state: 'active' }), ['Expires']],
    [
      'grace',
      row({ state: 'grace', graceEndsAt: GRACE_ENDS }),
      ['Paid period ended', 'Grace ends'],
    ],
    [
      'cancelled',
      row({ state: 'cancelled', cancelledAt: CANCELLED_AT }),
      ['Cancelled', 'Access ends'],
    ],
    ['expired', row({ state: 'expired' }), ['Access ended']],
  ])('draws exactly the rows %s owns', (_name, given, labels) => {
    const dates = boundaries(given)
    expect(dates).not.toBeNull()

    expect(boundaryRows(dates!).map((each) => each.label)).toEqual(labels)
  })

  it('carries the value through to the row it belongs to', () => {
    const dates = boundaries(row({ state: 'grace', graceEndsAt: GRACE_ENDS }))

    expect(boundaryRows(dates!)).toEqual([
      { label: 'Paid period ended', at: EXPIRES },
      { label: 'Grace ends', at: GRACE_ENDS },
    ])
  })

  it('leaves the one absent value absent rather than dropping its row', () => {
    const dates = boundaries(row({ state: 'expired', expiresAt: null }))

    expect(boundaryRows(dates!)).toEqual([{ label: 'Access ended', at: null }])
  })
})

describe('what a state allows', () => {
  // The engine restarts a cycle in place from these two and refuses from the other three. Drawn
  // where it would be accepted, because a control that is always refused teaches people to ignore
  // refusals.
  it.each([
    ['trial', false],
    ['active', false],
    ['grace', false],
    ['expired', true],
    ['cancelled', true],
  ] as const)('offers a new subscription on %s: %s', (state, allowed) => {
    expect(canStartNewSubscription(state)).toBe(allowed)
  })

  // A payment on a cancelled record is filed and applies to nothing — `payment.recorded` and
  // `payment.unmatched`, and the subscription untouched.
  it.each([
    ['trial', true],
    ['active', true],
    ['grace', true],
    ['expired', true],
    ['cancelled', false],
  ] as const)('lets a payment apply on %s: %s', (state, allowed) => {
    expect(paymentWouldApply(state)).toBe(allowed)
  })
})
