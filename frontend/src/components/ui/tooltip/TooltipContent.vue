<script setup lang="ts">
import type { TooltipContentEmits, TooltipContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TooltipContent, TooltipPortal, useForwardPropsEmits } from "reka-ui"
import { cn } from "@/lib/utils"

defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<TooltipContentProps & { class?: HTMLAttributes["class"] }>(), {
  sideOffset: 4,
})

const emits = defineEmits<TooltipContentEmits>()

const delegatedProps = reactiveOmit(props, "class")
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <TooltipPortal>
    <!-- @vue-expect-error `exactOptionalPropertyTypes` against a third party's prop types.
         Reka declares its optional props as `p?: T` rather than `p?: T | undefined`, and this
         wrapper forwards ours straight through, so a key that is present and undefined is a type
         error here and nowhere else. The setting is right for our own code and stays on; this is
         the one seam where it meets somebody else's declarations. -->
    <TooltipContent
      data-slot="tooltip-content"
      v-bind="{ ...forwarded, ...$attrs }"
      :class="
        cn(
          `z-50 w-fit max-w-reading rounded-panel border border-border-strong
           bg-surface-2 px-3 py-2 text-caption text-text-primary text-balance`,
          props.class,
        )
      "
    >
      <slot />

      <!-- NO MOTION, WHICH IS A DECISION AND NOT AN OMISSION.
           The generated version faded and scaled on the way in. Both are gone: the four hundred
           milliseconds before it opens already make it deliberate, and a panel that arrives
           instantly after a deliberate pause needs nothing to announce itself. It also means
           `prefers-reduced-motion` is honoured by construction rather than by a second rule that
           has to be remembered — there is nothing here to reduce. Anybody adding a transition
           later is making a motion decision, which belongs in docs/design.md first. -->

      <!-- No arrow. It would need a fill matching the panel and a stroke matching its border, and
           a rotated square cannot have both without drawing over one of them. The panel sits on
           --surface-2 against --surface-0 with a --border-strong outline, which is how
           docs/design.md says a floating layer separates itself; the arrow was carrying none of
           that work. -->
    </TooltipContent>
  </TooltipPortal>
</template>
