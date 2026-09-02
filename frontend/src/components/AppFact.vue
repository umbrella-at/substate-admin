<script setup lang="ts">
/**
 * A label and its value, stacked.
 *
 * The one shape for "here is a fact about this subscriber". Stacked rather than side by side: a
 * column of labels down the left is a second grid to keep aligned, and the value is the thing
 * being read.
 *
 * `numeric` is the Typography rule applied rather than a style choice — a date, an amount, an id,
 * a plan id and a promo code are all compared against something else on the screen, and
 * proportional digits make two values of the same length look different lengths.
 */

defineProps<{
  label: string
  /** Set for a value compared against another: dates, amounts, ids, codes. */
  numeric?: boolean
}>()
</script>

<template>
  <div>
    <dt class="text-caption text-text-muted">{{ label }}</dt>
    <dd
      class="mt-1 text-ui text-text-primary"
      :class="numeric === true ? 'font-numeric tabular-nums' : ''"
    >
      <slot />
    </dd>
  </div>
</template>
