<script setup lang="ts">
/**
 * One rectangle of a loading placeholder.
 *
 * It takes no width or height prop. A block that is waiting shows the shape of what is coming, and
 * only the screen knows that shape, so the caller sizes it with the ordinary utilities and this
 * component owns the fill, the corner and the pulse. Passing `h="20px"` through a prop would be the
 * same hardcoded number with one more indirection in front of it.
 *
 * The pulse itself is in tokens.css: between the two skeleton fills rather than through opacity,
 * and flat under `prefers-reduced-motion` — still visibly a placeholder, simply not moving.
 */
</script>

<template>
  <div class="skeleton rounded-control" aria-hidden="true" />
</template>
