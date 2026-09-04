import { describe, expect, it } from 'vitest'

import { daysWound, modelClock, modelDate } from '@/domain/clock'

describe('the moment a world is at', () => {
  it('reads as a day and a time of day, in UTC, saying so', () => {
    // Everything else the panel shows about a world is UTC. A clock in the reader's own zone next
    // to a table in UTC is an hour of arithmetic somebody has to do to compare two numbers.
    const at = Date.parse('2026-09-04T06:30:00Z')
    expect(modelDate(at)).toBe('4 Sept 2026')
    expect(modelClock(at)).toBe('06:30 UTC')
  })

  it('keeps a twenty-four hour clock', () => {
    expect(modelClock(Date.parse('2026-09-04T18:05:00Z'))).toBe('18:05 UTC')
  })

  it('is split so that a longer month name cannot move the line', () => {
    // The panel is 240px wide. One string wraps in September and not in October, and a reading
    // that jumps a line between two months looks broken in one of them.
    expect(modelDate(Date.parse('2026-09-04T06:30:00Z'))).not.toContain(':')
  })
})

describe('how far a world has been wound', () => {
  const DAY = 24 * 60 * 60 * 1000

  it('counts whole days and floors them', () => {
    // Floored, not rounded: an offset of thirty days and four seconds is thirty days. Rounding
    // would put "31 days ahead" on screen for a day that has not happened.
    expect(daysWound(30 * DAY + 4000)).toBe(30)
  })

  it('reads an exact month as a month', () => {
    // The reason this takes the offset rather than two clock readings. Model time is the real
    // clock plus the offset, so reading the real clock again a millisecond later and subtracting
    // gives just under thirty days — and a floor over that says 29.
    expect(daysWound(30 * DAY)).toBe(30)
  })

  it('is zero for a world nobody has wound', () => {
    expect(daysWound(0)).toBe(0)
  })

  it('never goes negative', () => {
    // The clock refuses to go backwards, so this cannot arise from the world. It can arise from
    // arithmetic, and "-1 days ahead" on screen would be worse than saying nothing.
    expect(daysWound(-DAY)).toBe(0)
  })
})
