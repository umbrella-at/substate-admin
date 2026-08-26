<script setup lang="ts">
import type { SelectValueProps } from "reka-ui"
import { SelectValue } from "reka-ui"

const props = defineProps<SelectValueProps>()
</script>

<template>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
  <SelectValue
    data-slot="select-value"
    v-bind="props"
  >
    <slot />
  </SelectValue>
</template>
