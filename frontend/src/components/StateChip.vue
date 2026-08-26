<script setup lang="ts">
/**
 * A subscription state, drawn as the round chip docs/design.md reserves for exactly this.
 *
 * The round shape is the one piece of vocabulary the design file spends on a single meaning: it is
 * how a state is recognised down a column before any of it is read, and every other pill on screen
 * would spend a little of that recognition. `scripts/check-design.sh` enforces that by name — this
 * file is the sole exception, and `rounded-full` anywhere else fails the build.
 *
 * The five states are a closed set the backend already validates, so the colour lookup is total.
 * There is no fallback branch, because a sixth state is a schema change and should arrive as a
 * type error here rather than as a grey chip nobody notices.
 */

import type { components } from '@/api/schema'

type SubscriptionState = components['schemas']['SubscriberSummary']['state']

const props = defineProps<{ state: SubscriptionState }>()

/** Colour and wording per state, both from docs/design.md.
 *
 *  The label is not the code. "In grace" and "Cancelled" are what an administrator would say out
 *  loud, and the column is read by people deciding who to call, not by people reading an enum.
 */
const APPEARANCE: Record<SubscriptionState, { label: string; classes: string }> = {
  trial: { label: 'Trial', classes: 'bg-state-trial-bg text-state-trial-text' },
  active: { label: 'Active', classes: 'bg-state-active-bg text-state-active-text' },
  grace: { label: 'In grace', classes: 'bg-state-grace-bg text-state-grace-text' },
  expired: { label: 'Expired', classes: 'bg-state-expired-bg text-state-expired-text' },
  cancelled: { label: 'Cancelled', classes: 'bg-state-cancelled-bg text-state-cancelled-text' },
}
</script>

<template>
  <span
    class="inline-block rounded-chip px-chip-x py-chip-y text-caption font-ui whitespace-nowrap"
    :class="APPEARANCE[props.state].classes"
  >
    {{ APPEARANCE[props.state].label }}
  </span>
</template>
