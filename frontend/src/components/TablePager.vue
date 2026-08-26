<script setup lang="ts">
/**
 * Which page of how many, and the two ways to move.
 *
 * The count is stated in people rather than pages. "241 subscribers" is the number somebody came
 * for; "page 3 of 10" is an artefact of how it is delivered. Both are here, in that order.
 *
 * The buttons are disabled at the ends rather than hidden, because a control that disappears
 * moves the one next to it under the cursor that was about to click it.
 */

import AppButton from '@/components/AppButton.vue'

const props = defineProps<{ page: number; pageCount: number; total: number; busy: boolean }>()
const emit = defineEmits<{ go: [number] }>()
</script>

<template>
  <div class="flex items-center justify-between gap-4 text-ui text-text-secondary">
    <!-- Announced politely: paging is the visitor's own action, so the new count should reach a
         screen reader without interrupting whatever it is reading. -->
    <p aria-live="polite">
      {{ props.total }} {{ props.total === 1 ? 'subscriber' : 'subscribers' }}
      <span v-if="props.pageCount > 1" class="text-text-muted">
        · page {{ props.page }} of {{ props.pageCount }}
      </span>
    </p>

    <div v-if="props.pageCount > 1" class="flex gap-2">
      <AppButton
        variant="outlined"
        :disabled="props.page <= 1 || props.busy"
        @click="emit('go', props.page - 1)"
      >
        Previous
      </AppButton>
      <AppButton
        variant="outlined"
        :disabled="props.page >= props.pageCount || props.busy"
        @click="emit('go', props.page + 1)"
      >
        Next
      </AppButton>
    </div>
  </div>
</template>
