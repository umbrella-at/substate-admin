<script setup lang="ts">
/**
 * The panel a figure lives in: the question, the answer, and the working underneath. A reader who
 * takes only the heading and the number has got the point.
 */

/* The caption names the source because two sit behind these figures — the engine holds what is
   true now, the journal holds what happened — and a reader comparing one with the subscriber
   table gets two correct numbers that differ. */

import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'

defineProps<{
  question: string
  /** What the figure answers, in one value. Absent while there is nothing to answer with. */
  answer?: string | undefined
  /** `standing now` or `movements in the period`, per docs/design.md. */
  source: string
  pending: boolean
  failed: boolean
  failure?: string | undefined
  /** True when the request succeeded and there is nothing in the answer to draw. */
  empty?: boolean | undefined
  /** What would put something here. Not "no data", which describes the panel. */
  invitation?: string | undefined
  busy?: boolean | undefined
  /** One sentence under the plot, for a fact the figure carries but does not draw. */
  note?: string | undefined
}>()

defineEmits<{ retry: [] }>()
</script>

<template>
  <section class="flex flex-col gap-3 rounded-panel bg-surface-1 p-4">
    <header class="flex flex-col gap-1">
      <h2 class="text-heading text-text-primary">{{ question }}</h2>
      <p class="text-caption text-text-muted">{{ source }}</p>
    </header>

    <template v-if="pending">
      <p class="sr-only" role="status">Loading {{ question }}</p>
      <SkeletonBlock class="h-6 w-2/5" />
      <SkeletonBlock class="h-chart-plot w-full" />
    </template>

    <template v-else-if="failed">
      <AppNotice assertive>{{ failure }}</AppNotice>
      <div>
        <AppButton variant="outlined" :busy="busy" @click="$emit('retry')">
          {{ busy ? 'Trying…' : 'Try again' }}
        </AppButton>
      </div>
    </template>

    <template v-else-if="empty">
      <p class="max-w-reading text-ui text-text-secondary">{{ invitation }}</p>
    </template>

    <template v-else>
      <p v-if="answer !== undefined" class="text-title font-numeric text-text-primary">
        {{ answer }}
      </p>
      <div :class="busy ? 'opacity-60' : ''">
        <slot />
      </div>
      <p v-if="note !== undefined" class="max-w-reading text-caption text-text-muted">{{ note }}</p>
    </template>
  </section>
</template>
