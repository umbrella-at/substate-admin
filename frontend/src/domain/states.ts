/**
 * The five subscription states, and everything the interface says about each of them.
 *
 * One place rather than one per component. The chip needs a label, a colour and a sentence; the
 * subscriber card in the next round needs the same three, and a filter needs the label. Spread
 * across templates, the sentence explaining GRACE would be written twice and would disagree with
 * itself the first time somebody improved one of them.
 *
 * The five are a closed set the backend already validates, so every lookup here is total. There is
 * no fallback entry, because a sixth state is a schema change and should arrive as a type error
 * rather than as a grey chip with no explanation.
 */

import type { components } from '@/api/schema'

export type SubscriptionState = components['schemas']['SubscriberSummary']['state']

export interface StateAppearance {
  /** What an administrator would say out loud. Not the code: this column is read by people
   *  deciding who to call, not by people reading an enum. */
  label: string
  /** One sentence, on the chip's tooltip. Two of the five look wrong until you have read it —
   *  CANCELLED carries a date in the future and GRACE one that has already passed — so the
   *  sentence has to say what the state means rather than restate its name. */
  meaning: string
  /** From docs/design.md's subscription-state palette, which is the only place these live. */
  classes: string
}

export const STATE_APPEARANCE: Record<SubscriptionState, StateAppearance> = {
  trial: {
    label: 'Trial',
    meaning: 'Free trial. No payment yet.',
    classes: 'bg-state-trial-bg text-state-trial-text',
  },
  active: {
    label: 'Active',
    meaning: 'Paid period is running.',
    classes: 'bg-state-active-bg text-state-active-text',
  },
  grace: {
    label: 'In grace',
    meaning: 'Paid period ended. Access extended as a courtesy.',
    classes: 'bg-state-grace-bg text-state-grace-text',
  },
  expired: {
    label: 'Expired',
    meaning: 'Access has ended. Waiting for a payment.',
    classes: 'bg-state-expired-bg text-state-expired-text',
  },
  cancelled: {
    label: 'Cancelled',
    meaning: 'Access runs to the end of the paid period, then stops.',
    classes: 'bg-state-cancelled-bg text-state-cancelled-text',
  },
}
