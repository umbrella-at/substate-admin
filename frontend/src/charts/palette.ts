/**
 * What a figure is drawn with, named rather than valued: the token's name is here, its value is
 * read off the stylesheet at draw time. `scripts/colours.py` fails a literal, and fails a name
 * the stylesheet does not declare — which resolves to the empty string and draws nothing.
 */

export type SeriesRole =
  | 'single'
  | 'joined'
  | 'left'
  | 'trial'
  | 'active'
  | 'grace'
  | 'expired'
  | 'cancelled'

/** A single series is accent; the two lines take the semantic roles for direction; the five
 *  states take the chips' TEXT colours, which a reader of the table already knows. */
export const SERIES: Readonly<Record<SeriesRole, string>> = {
  single: '--color-accent-text',
  joined: '--color-success-text',
  left: '--color-danger-text',
  trial: '--color-state-trial-text',
  active: '--color-state-active-text',
  grace: '--color-state-grace-text',
  expired: '--color-state-expired-text',
  cancelled: '--color-state-cancelled-text',
}

/** Everything that is not a mark. A tooltip is a floating layer and takes what Layout gives one.
 *  The two faces are here for the reason the colours are: a canvas takes a family by value, and
 *  Chart.js falls back to Helvetica without one. */
export const FURNITURE = {
  grid: '--color-border',
  tick: '--color-text-muted',
  legend: '--color-text-secondary',
  tooltipFill: '--color-surface-2',
  tooltipEdge: '--color-border-strong',
  tooltipText: '--color-text-primary',
  tickFace: '--font-numeric',
  labelFace: '--font-ui',
} as const

export type Reader = (name: string) => string

/** The stylesheet's own answer. A test hands in a reader of its own rather than a browser. */
export function fromDocument(name: string): string {
  if (typeof document === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function colour(role: SeriesRole, read: Reader = fromDocument): string {
  return read(SERIES[role])
}

export function furniture(part: keyof typeof FURNITURE, read: Reader = fromDocument): string {
  return read(FURNITURE[part])
}
