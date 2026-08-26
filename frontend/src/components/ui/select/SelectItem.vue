<script setup lang="ts">
import type { SelectItemProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { Check } from "@lucide/vue"
import { reactiveOmit } from "@vueuse/core"
import {
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  useForwardProps,
} from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<SelectItemProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")

const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
  <SelectItem
    data-slot="select-item"
    v-bind="forwardedProps"
    :class="
      cn(
        `relative flex w-full cursor-default items-center gap-2 select-none
         rounded-control py-2 pr-8 pl-2 text-ui outline-hidden
         data-[highlighted]:bg-accent-bg data-[highlighted]:text-accent-text
         data-[state=checked]:bg-accent-bg data-[state=checked]:text-accent-text
         data-[disabled]:pointer-events-none data-[disabled]:text-text-disabled
         [&_svg]:pointer-events-none [&_svg]:shrink-0
         [&_svg:not([class*='size-'])]:size-4
         *:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2`,
        props.class,
      )
    "
  >
    <span class="absolute right-2 flex size-4 items-center justify-center">
      <SelectItemIndicator>
        <slot name="indicator-icon">
          <Check class="size-4" />
        </slot>
      </SelectItemIndicator>
    </span>

    <SelectItemText>
      <slot />
    </SelectItemText>
  </SelectItem>
</template>
