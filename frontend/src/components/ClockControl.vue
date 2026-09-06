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

import { ApiError } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import AppNotice from '@/components/AppNotice.vue'
import { useWorldClock } from '@/composables/useWorldClock'
import { daysWound, modelClock, modelDate } from '@/domain/clock'

const client = useApiClient()
const queryClient = useQueryClient()
const { now, offsetMs, isSandbox, data: reading } = useWorldClock()

const busy = ref(false)
const refusal = ref('')
const custom = ref('')

/** The three the buttons offer. A month is thirty days rather than a calendar month: the engine
 *  counts periods in days, and "a month" here is a distance rather than a date on a wall. */
const UNMOVED = 'The world did not move. Try again in a moment.'

const STEPS = [
  { days: 1, label: 'Day' },
  { days: 7, label: 'Week' },
  { days: 30, label: 'Month' },
] as const

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

async function wind(days: number): Promise<void> {
  if (busy.value) return
  busy.value = true
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
    // The service's own sentence when it wrote one. A world that has been wound as far as it goes
    // says how much is left, and that number is the only thing that lets somebody choose a
    // smaller step — "the world did not move" would throw it away.
    refusal.value = cause instanceof ApiError && cause.message !== '' ? cause.message : UNMOVED
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section
    class="mt-6 rounded-panel border border-border bg-surface-2 p-3"
    aria-label="World clock"
  >
    <p class="text-caption text-text-muted">
      {{ isSandbox ? 'Your world' : 'The demonstration world' }}
    </p>
    <p class="mt-1 font-numeric text-ui text-text-primary">{{ day }}</p>
    <p class="font-numeric text-dense text-text-secondary">{{ time }}</p>
    <p v-if="ahead > 0" class="mt-1 text-caption text-text-muted">
      {{ ahead }} {{ ahead === 1 ? 'day' : 'days' }} ahead of today
    </p>

    <div class="mt-3 flex flex-wrap gap-1">
      <AppButton
        v-for="step in STEPS"
        :key="step.days"
        variant="outlined"
        :busy="busy"
        :disabled="step.days > left"
        @click="wind(step.days)"
      >
        {{ step.label }}
      </AppButton>
    </div>

    <form class="mt-2 flex items-end gap-2" novalidate @submit.prevent="asked && wind(asked)">
      <AppInput v-model="custom" class="min-w-0 flex-1" label="Days" placeholder="90" />
      <AppButton variant="outlined" type="submit" :busy="busy" :disabled="asked === null">
        Go
      </AppButton>
    </form>

    <!-- The one notice shape, like every other refusal in the application. The clock-read warning
         that used to be chained behind this one now sits in the frame, where everyone can see it
         — it is about every time on the page, and this control is drawn for hardly anybody. -->
    <AppNotice v-if="refusal !== ''" role="danger" class="mt-2">{{ refusal }}</AppNotice>
  </section>
</template>
