<script setup lang="ts">
import type { SelectContentEmits, SelectContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import {
  SelectContent,
  SelectPortal,
  SelectViewport,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from "@/lib/utils"
import { SelectScrollDownButton, SelectScrollUpButton } from "."

defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(
  defineProps<SelectContentProps & { class?: HTMLAttributes["class"] }>(),
  {
    position: "popper",
  },
)
const emits = defineEmits<SelectContentEmits>()

const delegatedProps = reactiveOmit(props, "class")

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <SelectPortal>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
    <SelectContent
      data-slot="select-content"
      v-bind="{ ...$attrs, ...forwarded }"
      :class="cn(
        `relative z-50 overflow-x-hidden overflow-y-auto
         max-h-(--reka-select-content-available-height)
         rounded-panel border border-border-strong bg-surface-2 text-text-primary`,
        position === 'popper'
          && 'data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1',
        props.class,
      )
      "
    >
      <SelectScrollUpButton />
      <SelectViewport :class="cn('p-1', position === 'popper' && 'h-(--reka-select-trigger-height) w-full min-w-(--reka-select-trigger-width) scroll-my-1')">
        <slot />
      </SelectViewport>
      <SelectScrollDownButton />
    </SelectContent>
  </SelectPortal>
</template>
