<script setup lang="ts">
/**
 * A subscription state, drawn as the round chip docs/design.md reserves for exactly this, with
 * the sentence that explains it.
 *
 * The round shape is the one piece of vocabulary the design file spends on a single meaning: it is
 * how a state is recognised down a column before any of it is read, and every other pill on screen
 * would spend a little of that recognition. `scripts/check-design.sh` enforces that by name — this
 * file is the sole exception, and `rounded-full` anywhere else fails the build.
 *
 * WHY THE CHIP CARRIES A SENTENCE. Two of the five raise the same question in everybody who meets
 * this table for the first time: a cancelled subscription whose date is in the future, and one in
 * grace whose date has already passed. Both are correct and neither is obvious, and the place to
 * answer that is on the row rather than in a document nobody has open.
 *
 * Not the native `title` attribute. It is drawn by the operating system, so it arrives in the
 * system's own styling on a dark panel, it waits about a second with no way to say otherwise, and
 * it never appears for somebody moving through the table by keyboard. The Reka tooltip underneath
 * `shadcn-vue`'s wrapper opens on focus as well as hover, which is the half that matters.
 */

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { STATE_APPEARANCE, type SubscriptionState } from '@/domain/states'

const props = defineProps<{ state: SubscriptionState }>()
</script>

<template>
  <Tooltip>
    <TooltipTrigger
      as="span"
      tabindex="0"
      class="inline-block rounded-chip px-chip-x py-chip-y text-caption font-ui whitespace-nowrap"
      :class="STATE_APPEARANCE[props.state].classes"
    >
      {{ STATE_APPEARANCE[props.state].label }}
    </TooltipTrigger>
    <!-- Beside the chip, not above it. A tooltip has to cover something, and above or below a
         36px panel lands squarely on the neighbouring row of a 68px table — the reader is then
         looking at a sentence about one subscriber laid over another one's state. To the side it
         stays inside its own row's band and covers the plan of the row being pointed at, which is
         the row the sentence is about. Reka flips it to the left near the edge on its own. -->
    <TooltipContent side="right" :side-offset="8">
      {{ STATE_APPEARANCE[props.state].meaning }}
    </TooltipContent>
  </Tooltip>
</template>
