<script setup lang="ts">
import type { SelectScrollDownButtonProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { ChevronDown } from "@lucide/vue"
import { reactiveOmit } from "@vueuse/core"
import { SelectScrollDownButton, useForwardProps } from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<SelectScrollDownButtonProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")

const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
  <SelectScrollDownButton
    data-slot="select-scroll-down-button"
    v-bind="forwardedProps"
    :class="cn('flex cursor-default items-center justify-center py-1', props.class)"
  >
    <slot>
      <ChevronDown class="size-4" />
    </slot>
  </SelectScrollDownButton>
</template>
