/**
 * What an event says, and the two ways this map can rot.
 *
 * It can lose a key, which the engine's own list catches — the record is total over thirteen and
 * a fourteenth type is a compile error at the record itself. And it can produce a sentence
 * containing `undefined`, which is what happens when a payload field is renamed upstream:
 * `journal.payload_of` reads `vars(event)`, so a rename arrives as a missing key rather than as a
 * failure, and only a test that reads the whole sentence notices.
 */

import { describe, expect, it } from 'vitest'

import {
  CHANGED_NOTHING,
  EVENT_SENTENCE,
  EVENT_TYPES,
  instant,
  isKnownEvent,
  moment,
  money,
  sentence,
  type EventType,
} from '@/domain/events'

/** One example per type, with the payload the engine actually writes. */
const PAYLOADS: Record<EventType, Record<string, unknown>> = {
  'subscription.created': { planId: 'monthly', state: 'trial' },
  'subscription.activated': { planId: 'monthly', expiresAt: '2026-10-16T00:00:00Z' },
  'subscription.renewed': { planId: 'annual', expiresAt: '2027-01-01T00:00:00Z' },
  'subscription.entering_grace': { graceEndsAt: '2026-09-14T00:00:00Z' },
  'subscription.expired': { reason: 'grace_ended' },
  'subscription.cancelled': { accessUntil: '2026-10-16T00:00:00Z' },
  'subscription.plan_changed': { planId: 'monthly', pendingPlanId: 'annual' },
  'payment.recorded': { provider: 'panel', externalId: 'ref-1', amount: 500 },
  'payment.duplicate': { provider: 'panel', externalId: 'ref-1' },
  'payment.underpaid': { provider: 'panel', externalId: 'ref-1', amount: 499, expected: 500 },
  'payment.unmatched': { provider: 'panel', externalId: 'ref-1', amount: 500 },
  'promo.redeemed': { code: 'LAUNCH20', kind: 'percent' },
  'referral.accrued': { referredUserId: 'sub-0123', programId: 'users', amount: 50 },
}

describe('the sentence map', () => {
  // The key set, stated here as well as in the type. A record that lost a key would be a compile
  // error; a record that gained one the engine does not emit would not, and that is a sentence
  // nobody will ever read sitting in a file everybody has to.
  it('covers the thirteen the engine emits, and nothing else', () => {
    expect(Object.keys(EVENT_SENTENCE).sort()).toEqual([...EVENT_TYPES].sort())
  })

  it.each(EVENT_TYPES)('says something complete about %s', (type) => {
    const said = sentence({ type, occurredAt: '2026-09-02T05:09:00Z', payload: PAYLOADS[type] })

    expect(said).not.toContain('undefined')
    expect(said).not.toContain('NaN')
    expect(said.endsWith('.')).toBe(true)
  })

  // The four reasons an expiry can have, each its own sentence. `grace_ended` and
  // `trial_not_converted` are different events for the person reading them.
  it.each([
    ['trial_not_converted', 'The trial ended without a payment.'],
    ['not_renewed', 'The paid period ended, and this plan has no grace.'],
    ['grace_ended', 'The grace period ran out. Access has ended.'],
    ['cancelled', 'The cancelled subscription reached the end of its paid period.'],
  ])('reads an expiry for %s as its own sentence', (reason, expected) => {
    expect(EVENT_SENTENCE['subscription.expired']({ reason })).toBe(expected)
  })

  // The payload carries a code and a kind and never a value, so the sentence names the kind and
  // stops. Reaching into the catalogue for today's percentage would make a row from March display
  // a number from September.
  it('never puts a discount amount on a redemption', () => {
    expect(EVENT_SENTENCE['promo.redeemed']({ code: 'LAUNCH20', kind: 'percent' })).toBe(
      'Redeemed LAUNCH20, a percentage discount.',
    )
  })

  // `user_id` on this event is the REFERRER, so on this subscriber's feed the row is money they
  // received. The voice is the only thing carrying that.
  it('reads a referral as money earned rather than money paid', () => {
    const said = EVENT_SENTENCE['referral.accrued'](PAYLOADS['referral.accrued'])

    expect(said).toBe("0.50 was earned from sub-0123's payment.")
  })

  it('says both halves of an underpayment', () => {
    expect(EVENT_SENTENCE['payment.underpaid'](PAYLOADS['payment.underpaid'])).toBe(
      '4.99 paid against 5.00 due. The period did not renew.',
    )
  })

  // The escape is visible rather than silent: `type` is an open string on the wire, so a later
  // engine emitting a fourteenth type must produce a legible row rather than an empty cell.
  it('names an event it has no wording for', () => {
    const said = sentence({ type: 'subscription.frozen', occurredAt: '2026-09-02Z', payload: {} })

    expect(said).toContain('subscription.frozen')
    expect(isKnownEvent('subscription.frozen')).toBe(false)
  })
})

describe('which outcomes moved nothing', () => {
  // A green notice over "Nothing changed" is a contradiction the eye reads before the words, so
  // the three that are a 200 and an unchanged subscription are named.
  it('is exactly the three payment outcomes that change no subscription', () => {
    expect([...CHANGED_NOTHING].sort()).toEqual([
      'payment.duplicate',
      'payment.underpaid',
      'payment.unmatched',
    ])
  })
})

describe('time', () => {
  it('writes a boundary as a date', () => {
    expect(moment('2026-09-09T14:07:00Z')).toBe('09 Sep 2026')
  })

  // The feed and the audit carry the time: two operations a minute apart are two rows somebody
  // has to tell apart, and a date alone made them identical.
  it('writes a feed entry as a date and a time', () => {
    expect(instant('2026-09-09T14:07:00Z')).toBe('09 Sep 2026 14:07')
  })

  // Every day-first English locale abbreviates September to four letters, which is a character
  // wider than every other month and breaks a column that exists to be scanned.
  it('gives every month three letters', () => {
    expect(moment('2026-09-10T00:00:00Z')).toBe('10 Sep 2026')
    expect(moment('2026-10-04T00:00:00Z')).toBe('04 Oct 2026')
  })

  it.each([null, '', 'not a date'])('answers an unreadable instant with a dash: %s', (given) => {
    expect(moment(given as string | null)).toBe('—')
    expect(instant(given as string | null)).toBe('—')
  })

  it('writes minor units as money, and keeps both decimals', () => {
    expect(money(500)).toBe('5.00')
    expect(money(4)).toBe('0.04')
    expect(money(123456)).toBe('1234.56')
  })
})
