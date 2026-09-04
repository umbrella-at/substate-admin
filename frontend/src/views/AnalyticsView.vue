<script setup lang="ts">
/**
 * Five figures, one question each, and every number with an event behind it. Five requests rather
 * than one, so a figure that failed says so where it is instead of blanking the four beside it.
 */

/* No filled control here. The rule about one filled element is about actions, the figures spend
   the accent, and a screen with nothing to press should not carry a loud button. */

import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import AppButton from '@/components/AppButton.vue'
import BarFigure from '@/components/BarFigure.vue'
import ChartFrame from '@/components/ChartFrame.vue'
import LineFigure from '@/components/LineFigure.vue'
import WorldNotBuilt from '@/components/WorldNotBuilt.vue'
import { useAnalytics } from '@/composables/useAnalytics'
import { useWorld } from '@/composables/useWorld'
import { useWorldNow } from '@/composables/useWorldClock'
import {
  amount,
  bandLabel,
  biggestLoss,
  bucketLabel,
  counted,
  FUNNEL_STAGE_LABEL,
  MOVEMENTS,
  periodFromRoute,
  periodToRoute,
  PERIODS,
  STANDING,
  stateBars,
  total,
  type Preset,
} from '@/domain/analytics'
import { money } from '@/domain/events'

const route = useRoute()
const router = useRouter()

const period = computed<Preset>(() => periodFromRoute(route.query['period']))

/** One moment for all the figures on one paint: a `now` that moved between two of them would put
 *  them on two periods invisibly. Refreshed when the period changes, because a tab left open for a
 *  day was otherwise asking about the thirty days ending yesterday. */

/* THE WORLD'S MOMENT, NOT THE BROWSER'S, AND THE CLOCK CONTROL IS WHY. A world wound a month
   forward has a last-thirty-days that ended a month ago in this browser, so the funnel, the flow
   and the revenue would describe the month before the visitor arrived, beside a table that moved. */
const worldNow = useWorldNow()
const now = ref(new Date(worldNow.value))
watch(worldNow, (moment) => {
  // Only when the world itself moves, not with the beat. A window that slid every ten seconds
  // would refetch five figures for a boundary nobody crossed.
  if (Math.abs(moment - now.value.getTime()) > A_DAY) now.value = new Date(moment)
})

/** A day, which is the coarsest thing any of these periods measures in. */
const A_DAY = 24 * 60 * 60 * 1000

const { funnel, flow, states, quiet, revenue } = useAnalytics(period, now)
const { isUnbuilt: worldIsUnbuilt } = useWorld()

function choose(next: Preset): void {
  now.value = new Date(worldNow.value)
  void router.push({ query: periodToRoute(next) })
}

const UNREACHABLE = 'The service could not be reached.'

/** What to put on screen when a figure failed. A 401 never arrives here — the client's session
 *  hook has navigated by then — so this is a 5xx, a refusal, or no network at all. */
function failure(error: unknown): string {
  if (error instanceof ApiError && error.status < 500 && error.message !== '') return error.message
  return UNREACHABLE
}

const funnelBars = computed(() => {
  const stages = funnel.data.value?.stages ?? []
  return {
    labels: stages.map((stage) => FUNNEL_STAGE_LABEL[stage.stage] ?? stage.stage),
    values: stages.map((stage) => stage.count),
  }
})

const flowLines = computed(() => {
  const response = flow.data.value
  const points = response?.points ?? []
  return {
    labels: points.map((point) => bucketLabel(point.startsAt, response?.granularity ?? 'week')),
    joined: points.map((point) => point.joined),
    left: points.map((point) => point.left),
  }
})

/** Empty rather than absent while there is nothing yet: the frame decides whether the plot is
 *  drawn, and a second guard here would hide a broken chain from the test that looks for it. */
const bars = computed(() =>
  states.data.value === undefined
    ? { labels: [], values: [], roles: [] }
    : stateBars(states.data.value),
)

const quietBands = computed(() => {
  const bands = quiet.data.value?.bands ?? []
  return {
    labels: bands.map((band) => bandLabel(band.fromDays, band.toDays)),
    values: bands.map((band) => band.count),
  }
})

/** The currency the answer is said in, from the answer itself. */
const takings = computed(() => amount(revenue.data.value?.currency ?? ''))

const revenueBars = computed(() => {
  const months = revenue.data.value?.months ?? []
  return {
    labels: months.map((month) => month.startsAt),
    values: months.map((month) => month.amount),
  }
})
</script>

<template>
  <section class="flex flex-col gap-6 p-6">
    <header class="flex flex-col gap-2">
      <h1 class="text-title text-text-primary">Analytics</h1>
      <p class="max-w-reading text-ui text-text-secondary">
        Five questions about the world this panel is looking at. Every number here has an event the
        engine actually emitted behind it, which is why there is no sixth.
      </p>
    </header>

    <fieldset class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <legend class="sr-only">Period</legend>
      <span class="text-caption text-text-secondary" aria-hidden="true">Period</span>
      <AppButton
        v-for="preset in PERIODS"
        :key="preset.value"
        :variant="period.value === preset.value ? 'outlined' : 'plain'"
        :aria-pressed="period.value === preset.value"
        @click="choose(preset)"
      >
        {{ preset.label }}
      </AppButton>
    </fieldset>

    <WorldNotBuilt v-if="worldIsUnbuilt" />

    <!-- One gap between figures, not two. `gap-6` separates the header and the period control from
         the figures; the figures themselves sit `16px` apart, as cards do. -->
    <div v-else class="flex flex-col gap-4">
      <ChartFrame
        question="Who is arriving, and who is leaving?"
        :source="MOVEMENTS"
        :pending="flow.isPending.value"
        :failed="flow.isError.value"
        :failure="failure(flow.error.value)"
        :empty="
          flow.data.value !== undefined && total(flowLines.joined) + total(flowLines.left) === 0
        "
        invitation="Nothing joined or left in this period. A longer one will have movement in it."
        :busy="flow.isFetching.value"
        :answer="`${counted(total(flowLines.joined), 'arrival', 'arrivals')}, ${counted(total(flowLines.left), 'departure', 'departures')}`"
        note="These two do not subtract to a population: a subscriber who lapses and pays again ends a subscription without arriving a second time. What is standing now is the states figure."
        @retry="() => void flow.refetch()"
      >
        <LineFigure
          :labels="flowLines.labels"
          :series="[
            { label: 'Joined', values: flowLines.joined, role: 'joined' },
            { label: 'Left', values: flowLines.left, role: 'left', dashed: true },
          ]"
        />
      </ChartFrame>

      <div class="grid gap-4 lg:grid-cols-2">
        <ChartFrame
          question="Where do we lose them?"
          :source="MOVEMENTS"
          :pending="funnel.isPending.value"
          :failed="funnel.isError.value"
          :failure="failure(funnel.error.value)"
          :empty="funnel.data.value !== undefined && funnel.data.value.stages[0]?.count === 0"
          invitation="Nobody arrived in this period. A longer one will have somebody in it."
          :busy="funnel.isFetching.value"
          :answer="biggestLoss(funnel.data.value?.stages ?? [])"
          :note="
            funnel.data.value === undefined
              ? undefined
              : `${funnel.data.value.startedATrial} of them arrived on a plan with a trial; the rest were asked to pay at once.`
          "
          @retry="() => void funnel.refetch()"
        >
          <BarFigure
            title="Arrivals"
            horizontal
            roles="single"
            :labels="funnelBars.labels"
            :values="funnelBars.values"
          />
        </ChartFrame>

        <ChartFrame
          question="What is in the base right now?"
          :source="STANDING"
          :pending="states.isPending.value"
          :failed="states.isError.value"
          :failure="failure(states.error.value)"
          :empty="states.data.value?.total === 0"
          invitation="There are no subscriptions in this world yet."
          :busy="states.isFetching.value"
          :answer="counted(states.data.value?.total ?? 0, 'subscription', 'subscriptions')"
          @retry="() => void states.refetch()"
        >
          <BarFigure
            title="Subscriptions"
            horizontal
            :labels="bars.labels"
            :values="bars.values"
            :roles="bars.roles"
          />
        </ChartFrame>

        <ChartFrame
          question="Who pays but has stopped turning up?"
          :source="STANDING"
          :pending="quiet.isPending.value"
          :failed="quiet.isError.value"
          :failure="failure(quiet.error.value)"
          :empty="quiet.data.value?.total === 0"
          invitation="Everybody with a live subscription has been here in the last month."
          :busy="quiet.isFetching.value"
          :answer="counted(quiet.data.value?.total ?? 0, 'subscriber', 'subscribers')"
          @retry="() => void quiet.refetch()"
        >
          <BarFigure
            title="Subscribers"
            horizontal
            roles="single"
            :labels="quietBands.labels"
            :values="quietBands.values"
          />
        </ChartFrame>

        <ChartFrame
          question="How much money is coming in?"
          :source="MOVEMENTS"
          :pending="revenue.isPending.value"
          :failed="revenue.isError.value"
          :failure="failure(revenue.error.value)"
          :empty="revenue.data.value !== undefined && total(revenueBars.values) === 0"
          invitation="No payment has been recorded in the last twelve months."
          :busy="revenue.isFetching.value"
          :answer="
            revenue.data.value === undefined
              ? undefined
              : `${money(total(revenueBars.values))} ${revenue.data.value.currency}`
          "
          @retry="() => void revenue.refetch()"
        >
          <BarFigure
            title="Taken"
            roles="single"
            :labels="revenueBars.labels.map((iso) => bucketLabel(iso, 'month'))"
            :values="revenueBars.values"
            :format="takings"
            :tick="money"
          />
        </ChartFrame>
      </div>
    </div>
  </section>
</template>
