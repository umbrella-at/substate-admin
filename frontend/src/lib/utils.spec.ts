/**
 * `cn` keeps the classes it is given, when the classes are this project's own.
 *
 * The failure these pin is invisible from the source: the class is written, it compiles, and
 * `tailwind-merge` removes it before it reaches the element, because it recognises Tailwind's
 * stock names and this theme replaced them. `scripts/utilities.py` cannot catch it — the utility
 * does produce CSS — and neither can a screenshot, unless somebody happens to know what size the
 * text was supposed to be.
 */

import { describe, expect, it } from 'vitest'

import { cn } from './utils'

describe('cn', () => {
  // A size and a colour are two properties, not two answers to one question. Before the merge was
  // taught this scale, the tooltip's `text-caption text-text-primary` resolved to the colour alone
  // and the panel rendered at whatever size it inherited.
  it.each([
    ['text-caption text-text-primary'],
    ['text-ui text-text-secondary'],
    ['text-dense text-text-muted'],
    ['text-heading text-on-accent'],
    ['text-title text-danger-text'],
  ])('keeps a size alongside a colour in %s', (classes) => {
    const [size] = classes.split(' ')
    expect(cn(classes).split(' ')).toContain(size)
  })

  // And the other direction: two sizes, or two radii, are one question, and the last should win.
  it('still resolves a real conflict', () => {
    expect(cn('text-ui text-caption')).toBe('text-caption')
    expect(cn('rounded-control rounded-panel')).toBe('rounded-panel')
    expect(cn('px-3 px-4')).toBe('px-4')
  })

  // `rounded-card` rather than the chip's radius, which is what the state chip actually pairs
  // with these classes: `scripts/check-design.sh` greps for `rounded-chip` outside that one
  // component, and it does not know a string in a test is not a class on an element. The check is
  // blunt on purpose and the test does not need that particular radius to make its point.
  it('leaves a colour and a radius alone, being different questions', () => {
    expect(cn('rounded-card text-caption text-state-trial-text').split(' ')).toEqual([
      'rounded-card',
      'text-caption',
      'text-state-trial-text',
    ])
  })
})
