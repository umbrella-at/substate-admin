<script setup lang="ts">
import type { SelectTriggerProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { ChevronDown } from "@lucide/vue"
import { reactiveOmit } from "@vueuse/core"
import { SelectIcon, SelectTrigger, useForwardProps } from "reka-ui"
import { cn } from "@/lib/utils"

/** The generated component had a `size` prop selecting between `h-9` and `h-8`. Both were removed
 *  along with it: this project has no `--spacing-9`, so `h-9` compiled to nothing at all and the
 *  control was as tall as its text — twenty pixels — while `h-8` quietly worked. Height comes from
 *  padding here, the same `px-3 py-2` the text input uses, so the two line up by construction
 *  rather than by two numbers agreeing. */
const props = defineProps<SelectTriggerProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")
const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
  <SelectTrigger
    data-slot="select-trigger"
    v-bind="forwardedProps"
    :class="cn(
      `flex w-fit items-center justify-between gap-2 whitespace-nowrap
       rounded-control border border-control-border bg-surface-0 px-3 py-2
       text-ui text-text-primary
       data-[placeholder]:text-text-muted
       [&_svg]:pointer-events-none [&_svg]:shrink-0
       [&_svg:not([class*='size-'])]:size-4
       [&_svg:not([class*='text-'])]:text-text-muted
       disabled:cursor-not-allowed disabled:border-border disabled:bg-fill-disabled
       disabled:text-text-disabled`,
      props.class,
    )"
  >
    <slot />
    <SelectIcon as-child>
      <ChevronDown class="size-4 opacity-50" />
    </SelectIcon>
  </SelectTrigger>
</template>
