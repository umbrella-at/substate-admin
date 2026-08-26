<script setup lang="ts">
import type { TooltipProviderProps } from "reka-ui"
import { TooltipProvider } from "reka-ui"

const props = withDefaults(defineProps<TooltipProviderProps>(), {
  // Not zero. A pointer crossing a column of chips would open and close five of these on the way
  // past; a short wait means a tooltip appears because somebody stopped, which is the only time it
  // is wanted. Keyboard focus is not delayed by this — Reka shows it at once, which is right,
  // because arriving on a control by keyboard is already deliberate.
  delayDuration: 400,
})
</script>

<template>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
  <TooltipProvider v-bind="props">
    <slot />
  </TooltipProvider>
</template>
