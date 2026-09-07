<script setup lang="ts">
/**
 * The time machine, in the frame rather than in a settings page. A subscription engine's whole
 * subject is time passing, and a panel over one that cannot move time is a set of screenshots.
 */

/* So it lives beside the navigation, on every screen, where somebody can press it and look at what
   changed on the page they were already reading. */

/* FORWARD ONLY, AND THE INTERFACE SAYS SO BY OFFERING NOTHING ELSE. The engine is built for
   monotonic time, the API refuses a backwards move, and a disabled "back" button would be a
   promise the service does not make. */

/* Every figure on every screen is read from this world, so an advance invalidates all of them.
   Naming the keys instead would be a list to keep in step with fifteen others, and the one that
   got missed would show a pre-advance number beside a post-advance table. */

import { useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { failureText } from '@/api/failure'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import AppNotice from '@/components/AppNotice.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import { useWorldClock } from '@/composables/useWorldClock'
import { daysWound, modelClock, modelDate } from '@/domain/clock'

const client = useApiClient()
const queryClient = useQueryClient()
const { now, offsetMs, isSandbox, data: reading, isPending } = useWorldClock()

const busy = ref(false)
const refusal = ref('')
const custom = ref('')

/** The three the buttons offer. A month is thirty days rather than a calendar month: the engine
 *  counts periods in days, and "a month" here is a distance rather than a date on a wall. */
const UNMOVED = 'The world did not move. Try again in a moment.'

const STEPS = [
  { id: 'day', days: 1, label: 'Day', winding: 'A day on…' },
  { id: 'week', days: 7, label: 'Week', winding: 'A week on…' },
  { id: 'month', days: 30, label: 'Month', winding: 'A month on…' },
] as const

/** The one docs/design.md names, and the one this control is marked by. */
const MONTH = 'month'

/** WHICH CONTROL IS OUT, keyed by the control rather than by the number it sends. Keyed by days,
 *  typing 30 into the field renamed the Month step for a press made on Go. */
const winding = ref<string | null>(null)

const day = computed(() => modelDate(now.value))
const time = computed(() => modelClock(now.value))
const ahead = computed(() => daysWound(offsetMs.value))

/** What the field holds, as a number of days, or null when it is not one this control may send.
 *  The API refuses the same range; this is what stops a press that was never going to work. */
const asked = computed(() => {
  const days = Number(custom.value.trim())
  if (!Number.isInteger(days) || days < 1 || days > left.value) return null
  return days
})

/** How much of the winding allowance the world has left, as the service reports it. Until the
 *  reading arrives, the whole of it: the refusal is the authority, this only saves a press. */
const left = computed(() => reading.value?.daysLeft ?? 365)

async function wind(days: number, control: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  winding.value = control
  refusal.value = ''
  try {
    const reached = await client.advanceClock(days)
    // Written straight in rather than refetched, so the times on screen move with the press
    // instead of a request later. The invalidation below deliberately spares this key.
    queryClient.setQueryData(['clock'], reached)
    await queryClient.invalidateQueries({
      predicate: (query) => query.queryKey[0] !== 'clock',
    })
    custom.value = ''
  } catch (cause) {
    // The service's own sentence when it wrote one, through the one helper that decides that. A
    // world wound as far as it goes says how much is left, and that number is the only thing that
    // lets somebody choose a smaller step.
    refusal.value = failureText(cause, UNMOVED)
  } finally {
    busy.value = false
    winding.value = null
  }
}
</script>

<template>
  <!-- THE SIGNATURE ELEMENT, and its boldness is spent on the reading rather than on a fill: a
       filled button in the frame is a filled button on every screen, and there is one per screen
       already. See docs/design.md, "Signature element". -->
  <section
    class="mt-6 rounded-panel border border-border bg-surface-2 p-3"
    :class="ahead > 0 ? 'border-l-2 border-l-accent-text' : ''"
    aria-label="World clock"
  >
    <!-- The reading has a loading state because it is the one number on this panel that is the
         subject. Without one it drew the BROWSER's date under the label "The demonstration
         world" — a confident answer to the question the control exists to ask. -->
    <template v-if="isPending">
      <p class="sr-only" role="status">Reading this world's clock</p>
      <SkeletonBlock class="h-3 w-12" />
      <SkeletonBlock class="mt-1 h-6 max-w-form" />
      <SkeletonBlock class="mt-1 h-3 w-12" />
    </template>

    <template v-else>
      <p class="text-caption text-text-muted">
        {{ isSandbox ? 'Your world' : 'The demonstration world' }}
      </p>
      <p class="mt-1 font-numeric text-title text-text-primary">{{ day }}</p>
      <p class="font-numeric text-dense text-text-secondary">{{ time }}</p>
      <p v-if="ahead > 0" class="mt-1 text-caption text-accent-text">
        {{ ahead }} {{ ahead === 1 ? 'day' : 'days' }} ahead of today
      </p>
    </template>

    <div class="mt-3 flex flex-wrap gap-1">
      <AppButton
        v-for="step in STEPS"
        :key="step.days"
        variant="outlined"
        :marked="step.id === MONTH"
        :busy="winding === step.id"
        :disabled="step.days > left"
        @click="wind(step.days, step.id)"
      >
        {{ winding === step.id ? step.winding : step.label }}
      </AppButton>
    </div>

    <form class="mt-2 flex items-end gap-2" novalidate @submit.prevent="asked && wind(asked, 'go')">
      <AppInput v-model="custom" class="min-w-0 flex-1" label="Days" placeholder="90" />
      <AppButton
        variant="outlined"
        type="submit"
        :busy="winding === 'go'"
        :disabled="asked === null"
      >
        {{ winding === 'go' ? 'Winding…' : 'Go' }}
      </AppButton>
    </form>

    <!-- The one notice shape, like every other refusal in the application. The clock-read warning
         that used to be chained behind this one now sits in the frame, where everyone can see it
         — it is about every time on the page, and this control is drawn for hardly anybody. -->
    <AppNotice v-if="refusal !== ''" role="danger" class="mt-2">{{ refusal }}</AppNotice>
  </section>
</template>
