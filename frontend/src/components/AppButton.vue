<script setup lang="ts">
/**
 * The one button.
 *
 * Three variants and no colour prop: a component that accepts `#2C5F87` is a component that will
 * one day be handed `#2C5F88`. What the caller chooses is the RANK of the action, and the tokens
 * decide what that rank looks like.
 *
 * `busy` is not `disabled`, and the distinction is docs/design.md's rather than a preference.
 * Disabled means the action is unavailable. A button waiting on a request keeps every colour it
 * had, says so in its label, carries `aria-busy`, and stays focusable — a control that greys out
 * for two hundred milliseconds and comes back reads as a flinch. Refusing the second click is the
 * handler's job, not the paint's, so `busy` deliberately does NOT set the `disabled` attribute.
 */

const {
  variant = 'plain',
  type = 'button',
  disabled = false,
  busy = false,
} = defineProps<{
  /** The rank of the action. At most ONE `filled` element may exist on a screen. */
  variant?: 'filled' | 'outlined' | 'plain'
  type?: 'button' | 'submit'
  /** The action cannot be performed at all. Not for "a request is in flight". */
  disabled?: boolean
  /** A request this button started has not answered yet. */
  busy?: boolean
}>()

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-control px-4 py-2 text-ui font-ui ' +
  'transition-colors duration-200 motion-reduce:transition-none'

const VARIANTS = {
  filled: 'bg-accent-fill text-on-accent hover:bg-accent-fill-hover',
  outlined:
    'border border-border-strong text-text-secondary hover:border-accent-text hover:text-text-primary',
  plain: 'text-text-secondary hover:text-text-primary',
} as const

// Neutral rather than a dimmed accent, because more than one kind of control gets disabled and
// most of them have no accent fill to dim. The border is stated for every variant so an outlined
// button does not keep a live outline around dead text.
const DISABLED = 'bg-fill-disabled text-text-disabled border border-border cursor-not-allowed'
</script>

<template>
  <button
    :type="type"
    :class="[BASE, disabled ? DISABLED : VARIANTS[variant]]"
    :disabled="disabled"
    :aria-busy="busy ? 'true' : undefined"
  >
    <slot />
  </button>
</template>
