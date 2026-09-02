/**
 * The one place the flat wire type becomes a tagged union.
 *
 * The API sends `trialEndsAt`, `expiresAt` and `graceEndsAt` as `string | null` on every state,
 * and the backend nulls the ones a state does not own — a runtime invariant `build_row` documents
 * and a test asserts, and one `vue-tsc` cannot see. So the card would be hiding rows on a promise
 * rather than on a type, and the first component to read `graceEndsAt` on an ACTIVE row would
 * compile.
 *
 * `boundaries()` closes that. It is the only place the flat shape is read, it returns a union
 * whose arms carry exactly the fields their state has, and it is consumed by a `switch` with no
 * `default` arm — so a sixth state is a build failure at that switch rather than a blank region on
 * a screen.
 */

import type { SubscriptionState } from '@/domain/states'
import type { SubscriberSummary } from '@/domain/subscribers'

/** What a subscription's dates are, per state.
 *
 *  `graceEndsAt` exists on exactly one arm. Writing it anywhere else is a compile error, which is
 *  the whole point: the type says which questions this state can be asked. */
export type Boundaries =
  | { state: 'trial'; trialEndsAt: string }
  | { state: 'active'; expiresAt: string }
  | { state: 'grace'; expiresAt: string; graceEndsAt: string }
  | { state: 'cancelled'; cancelledAt: string; expiresAt: string }
  // The one arm that admits an absence, and it is the same absence the table's `Access until`
  // column draws an em dash for: a subscription that ended without a payment ever being made.
  | { state: 'expired'; expiresAt: string | null }

/** One row of the boundary block: what to call the date, and the date. */
export interface BoundaryRow {
  label: string
  at: string | null
}

/**
 * The dates this row's state actually has, or `null` when the row contradicts itself.
 *
 * Null is not "no dates". It is a row whose state claims a boundary the engine says that state
 * always has, arriving without it — an ACTIVE subscription with no expiry. That combination cannot
 * be produced by `substate`, so it means the panel and the service disagree, and the card says so
 * rather than inventing a shape for it. Returning a half-filled union here is how an impossible
 * state becomes representable again one layer further in.
 */
export function boundaries(row: SubscriberSummary): Boundaries | null {
  switch (row.state) {
    case 'trial':
      return row.trialEndsAt === null || row.trialEndsAt === undefined
        ? null
        : { state: 'trial', trialEndsAt: row.trialEndsAt }
    case 'active':
      return row.expiresAt === null || row.expiresAt === undefined
        ? null
        : { state: 'active', expiresAt: row.expiresAt }
    case 'grace':
      return row.expiresAt === null ||
        row.expiresAt === undefined ||
        row.graceEndsAt === null ||
        row.graceEndsAt === undefined
        ? null
        : { state: 'grace', expiresAt: row.expiresAt, graceEndsAt: row.graceEndsAt }
    case 'cancelled':
      return row.cancelledAt === null ||
        row.cancelledAt === undefined ||
        row.expiresAt === null ||
        row.expiresAt === undefined
        ? null
        : { state: 'cancelled', cancelledAt: row.cancelledAt, expiresAt: row.expiresAt }
    case 'expired':
      return { state: 'expired', expiresAt: row.expiresAt ?? null }
  }
}

/**
 * The rows the card draws, in order, for the state it is in.
 *
 * The labels change with the state deliberately: a fixed label over a date that means "paid until"
 * in one state and "missed on" in another is a stable position holding an unstable meaning.
 * docs/design.md fixes this table.
 */
export function boundaryRows(dates: Boundaries): BoundaryRow[] {
  switch (dates.state) {
    case 'trial':
      return [{ label: 'Trial ends', at: dates.trialEndsAt }]
    case 'active':
      return [{ label: 'Expires', at: dates.expiresAt }]
    case 'grace':
      return [
        { label: 'Paid period ended', at: dates.expiresAt },
        { label: 'Grace ends', at: dates.graceEndsAt },
      ]
    case 'cancelled':
      return [
        { label: 'Cancelled', at: dates.cancelledAt },
        { label: 'Access ends', at: dates.expiresAt },
      ]
    case 'expired':
      return [{ label: 'Access ended', at: dates.expiresAt }]
  }
}

/** The states a new subscription can be started from.
 *
 *  The engine restarts a cycle in place from these two and refuses from the other three with
 *  `ALREADY_SUBSCRIBED`. Named here so the card can leave the control out rather than draw it and
 *  let the operator find out by being refused. */
const RESTARTABLE: ReadonlySet<SubscriptionState> = new Set(['expired', 'cancelled'])

export function canStartNewSubscription(state: SubscriptionState): boolean {
  return RESTARTABLE.has(state)
}

/**
 * Whether a payment on this subscription can do anything at all.
 *
 * On a cancelled record the engine files the money and changes nothing — `payment.recorded` and
 * `payment.unmatched`, and the subscription untouched. The control is drawn and disabled rather
 * than hidden, because "you cannot pay for a cancelled subscription" is a fact about this
 * subscriber worth reading, and a missing control says nothing at all.
 */
export function paymentWouldApply(state: SubscriptionState): boolean {
  return state !== 'cancelled'
}
