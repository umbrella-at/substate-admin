<script setup lang="ts">
/**
 * One shape for all three roles. A login error, an expired-session banner and a failed panel are
 * the same object wearing different colours, and three different shapes would say they are not.
 *
 * The width follows the container rather than a reading measure: a notice belongs to the thing it
 * is about, and one narrower than the panel it sits in reads as unrelated to it.
 */

type Role = 'danger' | 'warning' | 'success'

const { role = 'danger', assertive = false } = defineProps<{
  role?: Role
  /** `alert` interrupts a screen reader; `status` waits its turn. A refused sign-in is worth
   *  interrupting for, because the person is waiting on exactly that answer. */
  assertive?: boolean
}>()

const SHAPE: Record<Role, string> = {
  danger: 'border-danger-border bg-danger-bg text-danger-text',
  warning: 'border-warning-border bg-warning-bg text-warning-text',
  success: 'border-success-border bg-success-bg text-success-text',
}
</script>

<template>
  <div
    :class="[
      'flex items-start gap-2 rounded-control border px-3 py-2 text-dense',
      SHAPE[role],
    ]"
    :role="assertive ? 'alert' : 'status'"
  >
    <slot name="icon" />
    <div><slot /></div>
  </div>
</template>
