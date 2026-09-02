<script setup lang="ts">
/**
 * A labelled choice from a list, in the same anatomy as `AppField`.
 *
 * A list rather than a text field wherever the valid values are knowable: a plan id and a
 * programme id both come from a catalogue this panel can read, and a text field for either would
 * be a control whose right answer you learn by being refused.
 */

import { useId } from 'vue'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

defineProps<{
  label: string
  options: readonly { value: string; label: string }[]
  /** What the trigger says with nothing chosen. An empty trigger is a control that looks broken:
   *  it is narrow, unlabelled, and gives no reason to press it. */
  placeholder?: string
  help?: string | undefined
  error?: string | undefined
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
    <span :id="id" class="block text-caption text-text-secondary">{{ label }}</span>
    <div class="mt-2">
      <!-- Not `v-model`: the model may be undefined before the form initialises it, and Reka's
           Select does not accept undefined under `exactOptionalPropertyTypes`. Empty is what "no
           choice yet" looks like to it, and the write goes back through the setter unchanged. -->
      <Select
        :model-value="model ?? ''"
        :disabled="disabled"
        @update:model-value="(value) => (model = typeof value === 'string' ? value : undefined)"
      >
        <SelectTrigger :aria-labelledby="id" :aria-describedby="messageId">
          <SelectValue :placeholder="placeholder ?? 'Choose one'" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="option in options" :key="option.value" :value="option.value">
            {{ option.label }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
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
