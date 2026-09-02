<script setup lang="ts">
/**
 * A labelled control, its help and its error, in the anatomy docs/design.md fixes.
 *
 * Help and error occupy one place and never both at once: the error replaces the help while it is
 * on screen, so nothing below the control moves when a form is refused. A layout that shifts on
 * refusal makes the person look for what changed instead of reading what it says.
 *
 * OPTIONAL IS MARKED, REQUIRED IS NOT. These forms are mostly one required field, so marking the
 * exception is fewer marks than marking the rule — and an asterisk on almost everything is a mark
 * that stops being read.
 *
 * `AppInput` is not reused here: it owns its own model and renders no message, which is right for
 * the login page's one-sentence-per-form rule and wrong for a form whose refusals are per field.
 * The two are different components because they answer to different rules, not because one was
 * forgotten.
 */

import { useId } from 'vue'

const {
  label,
  type = 'text',
  help,
  error,
  optional = false,
  numeric = false,
  disabled = false,
} = defineProps<{
  label: string
  type?: 'text' | 'number'
  /** What this field is for, when the label cannot say it. Replaced by `error` while one exists. */
  help?: string | undefined
  error?: string | undefined
  optional?: boolean
  /** The mono cut, for a value compared against one already on the screen. */
  numeric?: boolean
  disabled?: boolean
}>()

// `string | undefined` because that is what VeeValidate's `defineField` hands over: a field
// has no value until the form initialises it. Narrowing it here would push a cast into
// every call site, which is the same unsoundness written six times instead of once.
const model = defineModel<string | undefined>({ required: true })

const id = useId()
const messageId = `${id}-message`
</script>

<template>
  <div>
    <label :for="id" class="block text-caption text-text-secondary">
      {{ label }}
      <span v-if="optional" class="text-text-muted">(optional)</span>
    </label>
    <input
      :id="id"
      v-model="model"
      :type="type"
      :disabled="disabled"
      :aria-invalid="error !== undefined ? 'true' : undefined"
      :aria-describedby="error !== undefined || help !== undefined ? messageId : undefined"
      class="mt-2 block w-full rounded-control border px-3 py-2 text-ui placeholder:text-text-muted"
      :class="[
        // One background and one text colour in the list, never two. Two utilities of the same
        // kind are resolved by the order Tailwind emitted them in, which is a fact about the
        // stylesheet rather than about this component — and `tailwind-merge` is not the answer
        // here, it drops this project's own sizes.
        disabled
          ? 'border-border bg-fill-disabled text-text-disabled'
          : error !== undefined
            ? 'border-danger-border bg-surface-0 text-text-primary'
            : 'border-control-border bg-surface-0 text-text-primary',
        numeric ? 'font-numeric tabular-nums' : '',
      ]"
    />
    <p
      v-if="error !== undefined"
      :id="messageId"
      class="mt-1 text-caption text-danger-text"
      role="alert"
    >
      {{ error }}
    </p>
    <p v-else-if="help !== undefined" :id="messageId" class="mt-1 text-caption text-text-muted">
      {{ help }}
    </p>
  </div>
</template>
