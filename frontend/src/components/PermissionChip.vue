<script setup lang="ts">
/**
 * A permission code, drawn as the fact it is.
 *
 * Not the round chip. docs/design.md gives that shape to the five subscription states and to
 * nothing else, because it is how a state is recognised before it is read, and every other pill on
 * screen spends a little of that recognition. A permission is not a state — it does not change on
 * its own, nobody has to be called about it — so it gets the square-cornered `surface-2` label.
 *
 * Mono because these are read down a column: `subscribers.read` against `subscribers.write` is a
 * comparison of endings, and proportional letterforms make two codes of the same length look like
 * different lengths.
 */

defineProps<{ code: string }>()
</script>

<template>
  <span
    class="inline-block rounded-control bg-surface-2 px-2 py-chip-y text-caption font-numeric text-text-secondary"
  >
    {{ code }}
  </span>
</template>
