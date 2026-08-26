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

import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import {
  COHORTS,
  DEFAULT_SORT,
  STATES,
  URGENCY_SORT,
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
 * So the text is held locally and released once the typing stops. Starting a search is a step
 * worth being able to come back from, so the first one pushes; refining it is not, so the rest
 * replace. Replacing all of them would mean the back button left the table entirely instead of
 * clearing the search, and pushing all of them is the per-letter history this exists to avoid.
 *
 * The watcher in the other direction is what keeps that honest: an address arriving from outside
 * — the back button, a pasted link, the clear button — has to reach the field, or the box would
 * go on showing a search that is no longer being applied.
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
  const refining = props.query.q !== null
  timer = setTimeout(() => apply({ q: next }, refining), SETTLE_MS)
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

function togglePlan(planId: string): void {
  const planIds = props.query.planIds.includes(planId)
    ? props.query.planIds.filter((entry) => entry !== planId)
    : [...props.query.planIds, planId]
  apply({ planIds })
}

/* THE ORDER HAS A NAME, SO IT IS OFFERED BY NAME.
 *
 * The State column used to carry a sort arrow. An arrow is a direction over a quantity — it says
 * this column runs from small to large — and a subscription state is not a quantity, so the glyph
 * promised an order it could not describe. What it actually produced was the alphabet: ACTIVE,
 * CANCELLED, EXPIRED, GRACE, TRIAL, which is the order of the letters and of nothing else.
 *
 * The order the table wants exists and is worth having, so it is here instead, wearing its name.
 * Not reversible: the reverse of "most urgent first" is a list of people there is nothing to do
 * about, which is not a thing anybody opens this table to see.
 */
const urgent = computed(
  () => props.query.sort.field === URGENCY_SORT.field && !props.query.sort.descending,
)

function toggleUrgency(): void {
  emit(
    'change',
    { ...props.query, page: 1, sort: urgent.value ? DEFAULT_SORT : URGENCY_SORT },
    { replace: false },
  )
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

    <fieldset id="filter-state" class="flex flex-col gap-2 scroll-mt-6">
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

    <fieldset id="filter-plan" class="flex flex-col gap-2 scroll-mt-6">
      <legend class="text-caption text-text-secondary">Plan</legend>
      <div class="flex flex-wrap gap-3">
        <label
          v-for="plan in props.plans"
          :key="plan"
          class="flex items-center gap-2 text-ui text-text-secondary"
        >
          <input
            type="checkbox"
            class="size-4 rounded-control accent-accent-fill"
            :checked="props.query.planIds.includes(plan)"
            @change="togglePlan(plan)"
          />
          <span class="font-numeric text-dense">{{ plan }}</span>
        </label>
      </div>
    </fieldset>

    <!-- Sorting, not filtering, and the only order control that is not a column header, because
         the order it turns on cannot be drawn as an arrow. Given its own caption for the same
         reason: sitting unlabelled next to the plan boxes, it read as a sixth plan. -->
    <fieldset class="flex flex-col gap-2 border-l border-border pl-4">
      <legend class="text-caption text-text-secondary">Order</legend>
      <label class="flex items-center gap-2 text-ui text-text-secondary">
        <input
          type="checkbox"
          class="size-4 rounded-control accent-accent-fill"
          :checked="urgent"
          @change="toggleUrgency"
        />
        Most urgent first
      </label>
    </fieldset>

    <AppButton variant="plain" @click="apply({ states: [], cohort: null, planIds: [], q: null })">
      Clear filters
    </AppButton>
  </form>
</template>
