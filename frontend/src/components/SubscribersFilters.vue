<script setup lang="ts">
/**
 * The filter bar.
 *
 * Every control emits a whole new question rather than mutating a shared object, because the
 * question lives in the URL and a partial update would be an address that disagrees with the
 * table. This component holds no state the address does not.
 *
 * Changing any filter goes back to page one. Staying on page seven while narrowing the result to
 * nine people shows an empty table under a working filter, which reads as "there is nobody" — the
 * most convincing wrong answer this screen can give.
 */

import { onBeforeUnmount, ref, watch } from 'vue'

import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import {
  COHORTS,
  STATES,
  type Cohort,
  type SubscriberQuery,
  type SubscriptionState,
} from '@/domain/subscribers'

const props = defineProps<{ query: SubscriberQuery; plans: string[] }>()

/** `replace` says whether this question deserves its own entry in the browser's history. Ticking
 *  a box does. The eleven intermediate spellings of a name being typed do not. */
const emit = defineEmits<{ change: [SubscriberQuery, { replace: boolean }] }>()

/** The one place that resets the page, so no caller can forget to. */
function apply(patch: Partial<SubscriberQuery>, replace = false): void {
  emit('change', { ...props.query, ...patch, page: 1 }, { replace })
}

/*
 * THE SEARCH FIELD IS THE ONE CONTROL THAT IS NOT A CLICK.
 *
 * Every other filter here produces one question per interaction. Typing produces one per
 * keystroke, and forwarding those directly would mean a request per character and — worse — a
 * history entry per character, so leaving a search would take as many presses of the back button
 * as the name had letters.
 *
 * So the text is held locally and released once the typing stops, as a replacement rather than a
 * new entry. The watcher in the other direction is what keeps that honest: an address arriving
 * from outside — the back button, a pasted link, the clear button — has to reach the field, or
 * the box would go on showing a search that is no longer being applied.
 */
const SETTLE_MS = 300

const text = ref(props.query.q ?? '')
let timer: ReturnType<typeof setTimeout> | undefined

watch(
  () => props.query.q,
  (incoming) => {
    const value = incoming ?? ''
    if (value === text.value) return
    clearTimeout(timer)
    text.value = value
  },
)

watch(text, (value) => {
  clearTimeout(timer)
  const trimmed = value.trim()
  const next = trimmed === '' ? null : trimmed
  if (next === props.query.q) return
  timer = setTimeout(() => apply({ q: next }, true), SETTLE_MS)
})

onBeforeUnmount(() => clearTimeout(timer))

function toggleState(state: SubscriptionState): void {
  const states = props.query.states.includes(state)
    ? props.query.states.filter((entry) => entry !== state)
    : [...props.query.states, state]
  apply({ states })
}

const STATE_LABELS: Record<SubscriptionState, string> = {
  trial: 'Trial',
  active: 'Active',
  grace: 'In grace',
  expired: 'Expired',
  cancelled: 'Cancelled',
}

function onCohort(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  apply({ cohort: value === '' ? null : (value as Cohort) })
}

function onPlan(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  apply({ planId: value === '' ? null : value })
}

const SELECT =
  'h-9 rounded-control border border-control-border bg-surface-0 px-3 text-ui text-text-primary'
</script>

<template>
  <!-- A form so Enter behaves the way the keyboard expects. It never submits: the address is
       written by the view, and letting the browser navigate would reload the page and throw away
       the cache along with it. -->
  <form class="flex flex-wrap items-end gap-4" @submit.prevent>
    <div class="w-full max-w-form">
      <AppInput v-model="text" label="Search" placeholder="Name or identifier" />
    </div>

    <fieldset class="flex flex-col gap-2">
      <legend class="text-caption text-text-secondary">State</legend>
      <div class="flex flex-wrap gap-3">
        <label
          v-for="state in STATES"
          :key="state"
          class="flex items-center gap-2 text-ui text-text-secondary"
        >
          <input
            type="checkbox"
            class="size-4 rounded-control accent-accent-fill"
            :checked="props.query.states.includes(state)"
            @change="toggleState(state)"
          />
          {{ STATE_LABELS[state] }}
        </label>
      </div>
    </fieldset>

    <label class="flex flex-col gap-2 text-caption text-text-secondary">
      Cohort
      <select :class="SELECT" :value="props.query.cohort ?? ''" @change="onCohort">
        <option value="">Everyone</option>
        <option v-for="cohort in COHORTS" :key="cohort.value" :value="cohort.value">
          {{ cohort.label }}
        </option>
      </select>
    </label>

    <label class="flex flex-col gap-2 text-caption text-text-secondary">
      Plan
      <select :class="SELECT" :value="props.query.planId ?? ''" @change="onPlan">
        <option value="">Any plan</option>
        <option v-for="plan in props.plans" :key="plan" :value="plan">{{ plan }}</option>
      </select>
    </label>

    <AppButton variant="plain" @click="apply({ states: [], cohort: null, planId: null, q: null })">
      Clear filters
    </AppButton>
  </form>
</template>
