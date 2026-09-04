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
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { STATE_APPEARANCE } from '@/domain/states'
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

/** The select carries a sentinel for "no cohort" rather than an empty string: an empty value in a
 *  Reka select is indistinguishable from nothing selected, and the placeholder would show where
 *  "Everyone" belongs. */
const EVERYONE = 'everyone'

function onCohort(value: unknown): void {
  apply({ cohort: value === EVERYONE || typeof value !== 'string' ? null : (value as Cohort) })
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
</script>

<template>
  <!-- A form so Enter behaves the way the keyboard expects. It never submits: the address is
       written by the view, and letting the browser navigate would reload the page and throw away
       the cache along with it.
       Four rows, and the grouping is the argument. Search and Cohort narrow the whole table, so
       they share a row. State and Plan are one question each, so each gets its own with its label
       beside it. Actions are not filters and sit apart at the bottom. -->

  <!-- Named, so it is a landmark. There is a second form in the frame now — the clock control —
       and "the form on this page" stopped identifying anything. -->
  <form class="flex flex-col gap-3" aria-label="Filters" @submit.prevent>
    <div class="flex flex-wrap items-end gap-4">
      <div class="w-full max-w-form">
        <AppInput v-model="text" label="Search" placeholder="Name or identifier" />
      </div>

      <label class="flex flex-col gap-2 text-caption text-text-secondary">
        Cohort
        <Select :model-value="props.query.cohort ?? EVERYONE" @update:model-value="onCohort">
          <!-- Content width. docs/design.md has no width step for a control that should be wider
               than its longest label, and inventing one here is how a design file stops being the
               place values come from. It grows leftward from the end of the row, so nothing moves
               with it. -->
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="EVERYONE">Everyone</SelectItem>
            <SelectItem v-for="cohort in COHORTS" :key="cohort.value" :value="cohort.value">
              {{ cohort.label }}
            </SelectItem>
          </SelectContent>
        </Select>
      </label>
    </div>

    <fieldset class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <legend class="sr-only">State</legend>
      <span class="w-12 text-caption text-text-secondary" aria-hidden="true">State</span>
      <label
        v-for="state in STATES"
        :key="state"
        class="flex items-center gap-2 text-ui text-text-secondary"
      >
        <Checkbox
          :model-value="props.query.states.includes(state)"
          @update:model-value="toggleState(state)"
        />
        {{ STATE_APPEARANCE[state].label }}
      </label>
    </fieldset>

    <fieldset class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <legend class="sr-only">Plan</legend>
      <span class="w-12 text-caption text-text-secondary" aria-hidden="true">Plan</span>
      <label
        v-for="plan in props.plans"
        :key="plan"
        class="flex items-center gap-2 text-ui text-text-secondary"
      >
        <Checkbox
          :model-value="props.query.planIds.includes(plan)"
          @update:model-value="togglePlan(plan)"
        />
        <span class="font-numeric text-dense">{{ plan }}</span>
      </label>
    </fieldset>

    <!-- Actions, not filters. Sorting and clearing both change the table without narrowing it, and
         standing them among the checkboxes is what made the order control read as a sixth plan. -->
    <div class="flex flex-wrap items-center gap-3">
      <AppButton :variant="urgent ? 'outlined' : 'plain'" @click="toggleUrgency">
        {{ urgent ? 'Sorted by urgency' : 'Sort by urgency' }}
      </AppButton>
      <AppButton variant="plain" @click="apply({ states: [], cohort: null, planIds: [], q: null })">
        Clear filters
      </AppButton>
    </div>
  </form>
</template>
