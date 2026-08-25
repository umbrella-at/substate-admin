<script setup lang="ts">
/**
 * A labelled text field.
 *
 * Inputs are recessed and buttons are raised — that is the whole control system in docs/design.md,
 * and it only works if the input has something to be recessed INTO. The fill here is `surface-0`,
 * which means this component is only correct inside a `surface-1` container or higher. Laid
 * straight on the page background it would match it exactly and survive as a rectangle of border:
 * technically visible, practically invisible.
 *
 * The label is a real `<label for>` rather than a placeholder. A placeholder disappears the moment
 * someone types, which is the moment they most need to know which field they are in, and it is
 * `text-muted` — the hint colour, not the label colour.
 *
 * This component does not render an error MESSAGE. On the login page every refusal produces one
 * sentence for the whole form, and a field that also spoke would either repeat it or contradict
 * it. `invalid` paints the border, `describedBy` points at whoever is doing the speaking.
 */

import { useId } from 'vue'

const {
  label,
  type = 'text',
  autocomplete,
  placeholder,
  invalid = false,
  describedBy,
  required = false,
} = defineProps<{
  label: string
  type?: 'text' | 'email' | 'password'
  autocomplete?: string | undefined
  placeholder?: string | undefined
  /** Paints the danger border and sets `aria-invalid`. The sentence lives elsewhere. */
  invalid?: boolean
  /** The id of the element that explains the current refusal, if one is on screen. */
  describedBy?: string | undefined
  required?: boolean
  /** Focus this field when the page opens. Only ever true for the first field of a page whose
   *  entire purpose is that form; anywhere else it steals the caret from someone reading. */
  autofocus?: boolean
}>()

const model = defineModel<string>({ required: true })

// Stable across server and client and unique per instance, so two fields never collide and the
// label always points at its own input.
const id = useId()
</script>

<template>
  <div>
    <label :for="id" class="block text-dense text-text-secondary">{{ label }}</label>
    <input
      :id="id"
      v-model="model"
      :type="type"
      :autocomplete="autocomplete"
      :placeholder="placeholder"
      :required="required"
      :autofocus="autofocus"
      :aria-invalid="invalid ? 'true' : undefined"
      :aria-describedby="describedBy"
      class="mt-2 block w-full rounded-control border bg-surface-0 px-3 py-2 text-ui text-text-primary placeholder:text-text-muted"
      :class="invalid ? 'border-danger-border' : 'border-border-strong'"
    />
  </div>
</template>
