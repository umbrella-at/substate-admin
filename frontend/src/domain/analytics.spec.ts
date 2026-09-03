/**
 * The screen's question and the sentences its figures answer with. The period is tested hardest:
 * it is the screen's only state, and a value the address does not carry is a link that opens on
 * a different figure from the one that was sent.
 */

import { describe, expect, it } from 'vitest'

import {
  bandLabel,
  biggestLoss,
  bucketLabel,
  counted,
  DEFAULT_PERIOD,
  monthLabel,
  periodFromRoute,
  periodParams,
  periodToRoute,
  PERIODS,
  total,
  weekLabel,
} from '@/domain/analytics'

describe('the period', () => {
  it('reads a preset the address names', () => {
    expect(periodFromRoute('30d')).toEqual(PERIODS[0])
    expect(periodFromRoute('12m')).toEqual(PERIODS[2])
  })

  // A value nobody offers is not a reason to show nothing. The screen has three answers and one
  // of them is the default, so anything else is read as "no preference stated".
  it('falls back to the default for anything it does not offer', () => {
    for (const raw of ['', 'yesterday', '1d', null, undefined, ['30d']]) {
      expect(periodFromRoute(raw)).toEqual(DEFAULT_PERIOD)
    }
  })

  // The address carries the question, not the answer to a question nobody asked. A default in it
  // makes two links to the same view that are not the same string.
  it('keeps the default out of the address and puts everything else in', () => {
    expect(periodToRoute(DEFAULT_PERIOD)).toEqual({})
    expect(periodToRoute(PERIODS[0]!)).toEqual({ period: '30d' })
  })

  it('round-trips every preset it offers', () => {
    for (const preset of PERIODS) {
      const route = periodToRoute(preset)
      expect(periodFromRoute(route['period'])).toEqual(preset)
    }
  })

  it('turns a preset into the two parameters the API takes', () => {
    const now = new Date('2026-09-03T12:00:00Z')
    const params = periodParams(PERIODS[0]!, now)
    expect(params.get('to')).toBe('2026-09-03T12:00:00.000Z')
    expect(params.get('from')).toBe('2026-08-04T12:00:00.000Z')
  })
})

describe('where the funnel loses them', () => {
  // The answer is the worst STEP, not the biggest number. A headline reading "168 arrived" would
  // be answering "how many came" under a heading that asks something else.
  it('names the largest drop rather than the largest stage', () => {
    const stages = [
      { stage: 'arrived', count: 168 },
      { stage: 'paid', count: 122 },
      { stage: 'renewed', count: 43 },
    ]
    expect(biggestLoss(stages)).toBe('79 of the 122 who paid did not renew')
  })

  it('names the first step when that is the one that loses most', () => {
    const stages = [
      { stage: 'arrived', count: 100 },
      { stage: 'paid', count: 10 },
      { stage: 'renewed', count: 8 },
    ]
    expect(biggestLoss(stages)).toBe('90 of the 100 who arrived did not pay')
  })

  it('says nothing when nobody arrived', () => {
    expect(biggestLoss([{ stage: 'arrived', count: 0 }])).toBeUndefined()
    expect(biggestLoss([])).toBeUndefined()
  })
})

describe('how a bucket is named', () => {
  // "Sept" is a character wider than every other abbreviation and is the one that collides on an
  // axis of twelve. The same rule the feed's dates follow, applied to a tick.
  it('cuts every month to three letters', () => {
    expect(monthLabel('2026-09-01T00:00:00Z')).toBe('Sep 26')
    expect(monthLabel('2026-08-01T00:00:00Z')).toBe('Aug 26')
  })

  it('names a week by the day it starts on', () => {
    expect(weekLabel('2026-08-31T00:00:00Z')).toBe('31 Aug')
  })

  it('takes the grain from the answer rather than guessing it', () => {
    expect(bucketLabel('2026-08-31T00:00:00Z', 'week')).toBe('31 Aug')
    expect(bucketLabel('2026-08-01T00:00:00Z', 'month')).toBe('Aug 26')
  })
})

describe('the sentences a figure says', () => {
  // How long, not since when: the same question the table's activity column answers.
  it('names a band by its length of silence, and the last one has no end', () => {
    expect(bandLabel(30, 60)).toBe('30 to 60 days')
    expect(bandLabel(90, null)).toBe('90 days or more')
  })

  it('agrees with its noun', () => {
    expect(counted(1, 'subscriber', 'subscribers')).toBe('1 subscriber')
    expect(counted(0, 'subscriber', 'subscribers')).toBe('0 subscribers')
    expect(counted(42, 'subscriber', 'subscribers')).toBe('42 subscribers')
  })

  it('adds nothing up to nothing', () => {
    expect(total([])).toBe(0)
    expect(total([1, 2, 3])).toBe(6)
  })
})
