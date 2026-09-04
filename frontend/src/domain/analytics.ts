/**
 * What the screen was asked for, and how its figures say their numbers. The period is a choice
 * from a list because `docs/design.md` has refused a date control in as many words; the API keeps
 * `from` and `to`, and this fills them in.
 */

/* In the address, like the table's question: a reload restores the view and the link travels. */

import type { FlowResponse, StatesResponse } from '@/api/client'
import type { SeriesRole } from '@/charts/palette'
import { money } from '@/domain/events'
import { STATE_APPEARANCE, type SubscriptionState } from '@/domain/states'

export interface Preset {
  value: string
  label: string
  days: number
}

/** Three, and the middle one is the default: long enough for a cohort to have converted and
 *  renewed, which is what makes the funnel worth reading, and short enough that a week is still
 *  a visible slice of it. */
export const PERIODS: readonly Preset[] = [
  { value: '30d', label: 'Last 30 days', days: 30 },
  { value: '90d', label: 'Last 90 days', days: 90 },
  { value: '12m', label: 'Last 12 months', days: 365 },
] as const

export const DEFAULT_PERIOD: Preset = PERIODS[1] as Preset

/** The revenue figure does not follow the selector. Its question is fixed at twelve months, and a
 *  figure whose period changed under a heading that did not would be answering something else. */
export const REVENUE_MONTHS = 12

export function periodFromRoute(raw: unknown): Preset {
  const value = typeof raw === 'string' ? raw : ''
  return PERIODS.find((preset) => preset.value === value) ?? DEFAULT_PERIOD
}

export function periodToRoute(preset: Preset): Record<string, string> {
  return preset.value === DEFAULT_PERIOD.value ? {} : { period: preset.value }
}

const DAY = 24 * 60 * 60 * 1000

/** `from` and `to` as the API names them, computed from the preset and the moment it was asked. */
export function periodParams(preset: Preset, now: Date): URLSearchParams {
  const params = new URLSearchParams()
  params.set('from', new Date(now.getTime() - preset.days * DAY).toISOString())
  params.set('to', now.toISOString())
  return params
}

/** Where each figure's numbers came from, under its heading, in the reader's words. */
export const STANDING = 'Standing now, from the engine'
export const MOVEMENTS = 'Movements in the period, from the event journal'

export const FUNNEL_STAGE_LABEL: Record<string, string> = {
  arrived: 'Arrived',
  paid: 'Paid at least once',
  renewed: 'Renewed at least once',
}

const REACHED: Record<string, string> = { arrived: 'arrived', paid: 'paid', renewed: 'renewed' }
const TO_REACH: Record<string, string> = { paid: 'pay', renewed: 'renew' }

/**
 * The largest step down, said as a sentence. "Where do we lose them" is answered by the worst
 * drop rather than by a total: a headline of who arrived answers "how many came".
 */
export function biggestLoss(
  stages: readonly { stage: string; count: number }[],
): string | undefined {
  let worst: {
    from: { stage: string; count: number }
    to: { stage: string; count: number }
  } | null = null
  for (let index = 1; index < stages.length; index += 1) {
    const from = stages[index - 1]
    const to = stages[index]
    if (from === undefined || to === undefined) continue
    if (worst === null || from.count - to.count > worst.from.count - worst.to.count) {
      worst = { from, to }
    }
  }
  if (worst === null || worst.from.count === 0) return undefined
  const lost = worst.from.count - worst.to.count
  return `${lost} of the ${worst.from.count} who ${REACHED[worst.from.stage]} did not ${TO_REACH[worst.to.stage]}`
}

const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'short', year: '2-digit', timeZone: 'UTC' })
const DAY_AND_MONTH = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  timeZone: 'UTC',
})

/** Three letters for the month, for the reason `domain/events.ts` gives: "Sept" is a character
 *  wider than every other abbreviation, and on an axis of twelve it is the one that collides. */
function threeLetterMonth(format: Intl.DateTimeFormat, at: Date): string {
  return format
    .formatToParts(at)
    .map((part) => (part.type === 'month' ? part.value.slice(0, 3) : part.value))
    .join('')
}

export function monthLabel(iso: string): string {
  return threeLetterMonth(MONTH, new Date(iso))
}

/** A week is named by the day it starts on: the axis is a sequence, and a range in every tick
 *  would double the label without saying anything the neighbouring tick does not. */
export function weekLabel(iso: string): string {
  return threeLetterMonth(DAY_AND_MONTH, new Date(iso))
}

export function bucketLabel(iso: string, granularity: FlowResponse['granularity']): string {
  return granularity === 'month' ? monthLabel(iso) : weekLabel(iso)
}

/** The five states in the order the server sends them, which is the table's order of urgency. */
export function stateBars(response: StatesResponse): {
  labels: string[]
  values: number[]
  roles: SeriesRole[]
} {
  return {
    labels: response.states.map(
      (entry) => STATE_APPEARANCE[entry.state as SubscriptionState].label,
    ),
    values: response.states.map((entry) => entry.count),
    roles: response.states.map((entry) => entry.state as SeriesRole),
  }
}

/** One band, said the way the column over the table says it: how long, not since when. */
export function bandLabel(from: number, to: number | null): string {
  return to === null ? `${from} days or more` : `${from} to ${to} days`
}

/** Minor units said with their unit. The unit belongs beside one number rather than beside six
 *  of them down the side of a plot, so the axis takes `money` and the tooltip takes this. */
export function amount(currency: string): (value: number) => string {
  return (value: number) => (currency === '' ? money(value) : `${money(value)} ${currency}`)
}

export function total(values: readonly number[]): number {
  return values.reduce((sum, value) => sum + value, 0)
}

/** A count said as a person would say it, with the noun that goes with the number. */
export function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}
