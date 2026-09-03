/**
 * The chart palette against the one the chips use. Nothing in the build connects a bar to the
 * chip it must match, so this does: a chip recoloured in `docs/design.md` moves the figure with
 * it, or fails here.
 */

import { describe, expect, it } from 'vitest'

import { colour, FURNITURE, furniture, SERIES } from '@/charts/palette'
import { STATE_APPEARANCE, type SubscriptionState } from '@/domain/states'

const STATES: SubscriptionState[] = ['trial', 'active', 'grace', 'expired', 'cancelled']

/** The token behind `text-state-grace-text`, which is how the chip asks for the same colour. */
function chipTextToken(state: SubscriptionState): string {
  const found = STATE_APPEARANCE[state].classes.split(' ').find((each) => each.startsWith('text-'))
  return `--color-${found?.slice('text-'.length) ?? ''}`
}

describe('the series palette', () => {
  it('gives every state the colour its chip is read by', () => {
    for (const state of STATES) {
      expect(SERIES[state], state).toBe(chipTextToken(state))
    }
  })

  it('names a token for every role and every piece of furniture, and never a value', () => {
    for (const name of [...Object.values(SERIES), ...Object.values(FURNITURE)]) {
      expect(name).toMatch(/^--color-[a-z0-9-]+$/)
    }
  })

  // Every mark on a figure must be one of the eight. A sixth state or a third line would arrive
  // as a type error at the call site rather than as an undefined colour on a canvas.
  it('has one role per mark a figure can draw', () => {
    expect(Object.keys(SERIES).sort()).toEqual(
      ['active', 'cancelled', 'expired', 'grace', 'joined', 'left', 'single', 'trial'].sort(),
    )
  })

  it('reads the value off the stylesheet rather than holding one', () => {
    const read = (name: string) => `resolved(${name})`
    expect(colour('single', read)).toBe('resolved(--color-accent-text)')
    expect(furniture('grid', read)).toBe('resolved(--color-border)')
  })
})
