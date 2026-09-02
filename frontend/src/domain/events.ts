/**
 * What an event says, in a sentence.
 *
 * The feed and the notice after an operation are the same problem: a reader has to be told what
 * happened, and the payload is where it is written. `{"reason":"grace_ended"}` is translated by
 * whoever reads it, worse and differently each time; putting the translation in one total record
 * makes it reviewable, testable by enumeration, and the same in both places.
 *
 * ONE MAP, TWO CONSUMERS. The notice after `Record a payment` is rendered from the events the
 * engine emitted rather than from the button that was pressed, so a duplicate reference and a
 * short payment — both 200s that changed nothing — say so for free. A notice written from the
 * button would say "Payment recorded" over a card that had not moved.
 *
 * NOTHING IS INVENTED FROM OUTSIDE THE ROW. `promo.redeemed` carries a code and a kind and never a
 * value, so the sentence names the kind and stops: reaching into the catalogue for today's
 * percentage would make a row from March display a number from September. Plan ids render as ids
 * for the same reason — the catalogue is a live thing and the row is history.
 */

import type { components } from '@/api/schema'

export type EngineEvent = components['schemas']['EngineEvent']

/** The thirteen `substate` emits. Written out rather than generated: it is the key set of the
 *  record below, and a type derived from the wire — where `type` is deliberately an open string —
 *  would make this record impossible to check. */
export const EVENT_TYPES = [
  'subscription.created',
  'subscription.activated',
  'subscription.renewed',
  'subscription.entering_grace',
  'subscription.expired',
  'subscription.cancelled',
  'subscription.plan_changed',
  'payment.recorded',
  'payment.duplicate',
  'payment.underpaid',
  'payment.unmatched',
  'promo.redeemed',
  'referral.accrued',
] as const

export type EventType = (typeof EVENT_TYPES)[number]

/** The outcomes that are a 200 and a subscription that did not move.
 *
 *  A green notice over "Nothing changed" is a contradiction the eye reads before the words, so
 *  what an operation says it did decides the colour it says it in. */
export const CHANGED_NOTHING: ReadonlySet<string> = new Set([
  'payment.duplicate',
  'payment.underpaid',
  'payment.unmatched',
])

const KNOWN: ReadonlySet<string> = new Set(EVENT_TYPES)

export function isKnownEvent(type: string): type is EventType {
  return KNOWN.has(type)
}

type Payload = Record<string, unknown>

function text(payload: Payload, key: string): string | null {
  const value = payload[key]
  return typeof value === 'string' && value !== '' ? value : null
}

function count(payload: Payload, key: string): number | null {
  const value = payload[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** An amount in minor units, as money.
 *
 *  No currency symbol. `Payment` has no currency field at all — the label lives on the plan, and
 *  the engine never reads it — so a symbol here would be the panel asserting something the event
 *  does not carry. The card names the currency once, beside the plan. */
export function money(minor: number): string {
  return (minor / 100).toFixed(2)
}

const DATE = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

const TIME = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'UTC',
})

/** The same absolute form the card's boundaries use, so the two can be compared by eye.
 *
 *  Assembled from parts for the one word every day-first English locale abbreviates to four
 *  letters: "Sept" is a character wider than every other month and breaks the column. */
export function moment(iso: string | null): string {
  const at = parsed(iso)
  return at === null ? '—' : day(at)
}

/**
 * The same date, plus the time it happened at.
 *
 * The feed and the audit are read for WHEN, and two operations a minute apart are two rows a
 * person has to tell apart. A date alone made them identical — found by performing the same
 * operation twice and looking at the result, which is the only thing that could have found it.
 *
 * A boundary keeps the date alone: `expiresAt` at 14:07 is a fact about a clock, not about the
 * subscription, and printing it invites a reader to compare minutes that mean nothing.
 */
export function instant(iso: string | null): string {
  const at = parsed(iso)
  return at === null ? '—' : `${day(at)} ${TIME.format(at)}`
}

function parsed(iso: string | null): Date | null {
  if (iso === null) return null
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? null : at
}

function day(at: Date): string {
  return DATE.formatToParts(at)
    .map((part) => (part.type === 'month' ? part.value.slice(0, 3) : part.value))
    .join('')
}

const EXPIRY_REASON: Record<string, string> = {
  trial_not_converted: 'The trial ended without a payment.',
  not_renewed: 'The paid period ended, and this plan has no grace.',
  grace_ended: 'The grace period ran out. Access has ended.',
  cancelled: 'The cancelled subscription reached the end of its paid period.',
}

const PROMO_KIND: Record<string, string> = {
  percent: 'a percentage discount',
  fixed: 'a fixed discount',
  plus_days: 'extra days',
}

/**
 * One sentence per event type. Total over the thirteen, with no fallback entry.
 *
 * The same construction and the same reason as `STATE_APPEARANCE`: a fourteenth type in a later
 * engine should arrive as a type error at this record rather than as a blank cell in a feed.
 */
export const EVENT_SENTENCE: Record<EventType, (payload: Payload) => string> = {
  'subscription.created': (p) => {
    const plan = text(p, 'planId') ?? 'a plan'
    // Only two states are reachable here: a plan with a trial starts in TRIAL, one without starts
    // expired and waiting for the first payment.
    return text(p, 'state') === 'trial'
      ? `Subscribed to ${plan}. Started as a trial.`
      : `Subscribed to ${plan}. Waiting for a first payment.`
  },
  'subscription.activated': (p) =>
    `Paid. ${text(p, 'planId') ?? 'The plan'} runs to ${moment(text(p, 'expiresAt'))}.`,
  'subscription.renewed': (p) =>
    `Renewed. ${text(p, 'planId') ?? 'The plan'} runs to ${moment(text(p, 'expiresAt'))}.`,
  'subscription.entering_grace': (p) =>
    `A payment did not arrive. Access is extended to ${moment(text(p, 'graceEndsAt'))}.`,
  'subscription.expired': (p) => {
    const reason = text(p, 'reason')
    return (reason !== null ? EXPIRY_REASON[reason] : undefined) ?? 'The subscription ended.'
  },
  'subscription.cancelled': (p) => {
    const until = text(p, 'accessUntil')
    return until === null
      ? 'Cancelled. No paid access remained.'
      : `Cancelled. Access runs to ${moment(until)}.`
  },
  'subscription.plan_changed': (p) => {
    const current = text(p, 'planId') ?? 'the current plan'
    const pending = text(p, 'pendingPlanId')
    return pending === null
      ? `The pending plan change was dropped. Staying on ${current}.`
      : `${current} becomes ${pending} at the next payment.`
  },
  'payment.recorded': (p) => {
    const amount = count(p, 'amount')
    return amount === null
      ? 'A payment was recorded.'
      : `A payment of ${money(amount)} was recorded.`
  },
  'payment.duplicate': (p) => {
    const reference = text(p, 'externalId')
    return reference === null
      ? 'That payment was already on file. Nothing changed.'
      : `A payment under reference ${reference} was already on file. Nothing changed.`
  },
  'payment.underpaid': (p) => {
    const paid = count(p, 'amount')
    const due = count(p, 'expected')
    return paid === null || due === null
      ? 'The payment was short of the price. The period did not renew.'
      : `${money(paid)} paid against ${money(due)} due. The period did not renew.`
  },
  'payment.unmatched': (p) => {
    const amount = count(p, 'amount')
    return amount === null
      ? 'A payment was filed with no subscription to apply it to.'
      : `${money(amount)} was filed with no subscription to apply it to.`
  },
  'promo.redeemed': (p) => {
    const code = text(p, 'code') ?? 'A code'
    const kind = text(p, 'kind')
    const what = (kind !== null ? PROMO_KIND[kind] : undefined) ?? 'a discount'
    return `Redeemed ${code}, ${what}.`
  },
  // `user_id` on this event is the REFERRER — the one whose balance grew — so on this
  // subscriber's feed the row is money they earned, and the voice has to say so.
  'referral.accrued': (p) => {
    const amount = count(p, 'amount')
    const from = text(p, 'referredUserId')
    const earned = amount === null ? 'A referral reward' : `${money(amount)}`
    return from === null
      ? `${earned} was earned from a referral.`
      : `${earned} was earned from ${from}'s payment.`
  },
}

/** What one event reads as.
 *
 *  The escape is visible rather than silent, and it is here because `type` is an open string on
 *  the wire: a later engine emitting a fourteenth type must produce a legible row rather than an
 *  empty cell, and the label is what tells whoever sees it that this map needs an entry. */
export function sentence(event: EngineEvent): string {
  if (!isKnownEvent(event.type)) return `${event.type} — this panel has no wording for this event.`
  return EVENT_SENTENCE[event.type](event.payload)
}
