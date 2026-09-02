<script setup lang="ts">
/**
 * The pause before something that cannot be undone from this screen.
 *
 * WHEN THIS EXISTS AT ALL. An operation is confirmed when a person cannot reverse its effect with
 * another operation on the same card, AND the consequence is not already stated by what they
 * typed. Everything else answers on the press and says what it will do inside the form, above the
 * button, where the decision is still being made — a dialog asks after the decision is taken.
 *
 * BOTH ACTIONS NAME THEMSELVES. The confirming button carries the verb the trigger carried and the
 * result will carry; the dismissing one names what stays true — `Keep subscription`, never
 * `Cancel`, which on a cancellation dialog would be one word for two opposite actions.
 *
 * The edge is `--control-border` and not `--border-strong`, and the scrim is not what makes it
 * visible: docs/design.md measures both. On this palette no scrim reaches 3:1 against the dialog's
 * fill, so the outline does the separating and the scrim says the page behind is not operable.
 */

import {
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogRoot,
  AlertDialogTitle,
} from 'reka-ui'

const props = defineProps<{
  /** The verb, as the trigger said it. `Cancel subscription`, not `Confirm`. */
  action: string
  /** The same verb while the request is out. `Cancelling the subscription…` */
  busyAction: string
  /** What stays true if they stop here. `Keep subscription`. */
  dismiss: string
  /** The consequence, with this subscriber's own dates in it. */
  title: string
  busy?: boolean
}>()

const open = defineModel<boolean>('open', { required: true })

const emit = defineEmits<{ confirm: [] }>()

function confirm(): void {
  if (props.busy === true) return
  emit('confirm')
}
</script>

<template>
  <!-- Not `v-model:open`. While the request is out this dialog may not close by ANY route — the
       dismissing button, Escape, a click outside — because each of them leaves the operation
       running and the dialog gone, which is the promise `Keep subscription` makes and cannot keep.
       Disabling the button closed one of the three; refusing the close closes all of them. -->
  <AlertDialogRoot
    :open="open"
    @update:open="(next: boolean) => (next || busy !== true ? (open = next) : undefined)"
  >
    <AlertDialogPortal>
      <AlertDialogOverlay class="fixed inset-0 z-40 bg-scrim" />
      <!-- Centred by transform rather than by a grid on the overlay: the overlay is the scrim and
           has no business owning the layout of what sits on it. -->
      <AlertDialogContent
        class="fixed top-1/2 left-1/2 z-40 w-full max-w-form -translate-x-1/2 -translate-y-1/2 rounded-card border border-control-border bg-surface-2 p-6"
      >
        <AlertDialogTitle class="text-heading text-text-primary">{{ action }}</AlertDialogTitle>
        <AlertDialogDescription class="mt-3 text-ui text-text-secondary">
          {{ title }}
        </AlertDialogDescription>

        <!-- Anything the caller wants between the sentence and the buttons: the danger notice
             lives here rather than as a red fill on the confirming button, because this file has
             no bright red surface and a sentence with a date in it is more specific than a colour. -->
        <slot />

        <div class="mt-6 flex justify-end gap-3">
          <!-- Focus starts on the way out. Someone who opened this by mistake presses the key they
               were already pressing and nothing happens.
               Unavailable once the confirm is out, and that is not decoration: it closed the
               dialog while the POST completed, so `Keep subscription` kept nothing. -->
          <AlertDialogCancel as-child :disabled="busy === true">
            <button
              type="button"
              :disabled="busy === true"
              class="inline-flex items-center justify-center rounded-control border px-4 py-2 text-ui transition-colors duration-200 motion-reduce:transition-none"
              :class="
                busy === true
                  ? 'cursor-not-allowed border-border bg-fill-disabled text-text-disabled'
                  : 'border-border-strong text-text-secondary hover:border-accent-text hover:text-text-primary'
              "
            >
              {{ dismiss }}
            </button>
          </AlertDialogCancel>
          <!-- Not `as-child` on a `<button>` that closes: the close has to wait for the request,
               and Reka's Action closes on click. The dialog is dismissed by whoever owns `open`. -->
          <button
            type="button"
            class="inline-flex items-center justify-center rounded-control bg-accent-fill px-4 py-2 text-ui text-on-accent transition-colors duration-200 hover:bg-accent-fill-hover motion-reduce:transition-none"
            :aria-busy="busy === true ? 'true' : undefined"
            @click="confirm"
          >
            {{ busy === true ? busyAction : action }}
          </button>
        </div>
      </AlertDialogContent>
    </AlertDialogPortal>
  </AlertDialogRoot>
</template>
