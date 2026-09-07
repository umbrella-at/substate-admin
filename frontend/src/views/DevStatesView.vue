<script setup lang="ts">
/** Every block on this panel, in all four of the states the specification requires of it. */

/* IT EXISTS BECAUSE THE RULE WAS UNCHECKABLE. Four states per figure, table and feed is the
   oldest rule in the specification, and the only way to look at three of them was to break the
   backend — so they were written once and never seen again. */

/* Dev build only, by the route that reaches it: `import.meta.env.DEV` is a constant Rollup folds
   away, so this file and its fixtures are not in the production bundle at all. */

/* Each case mounts the REAL screen over a service that answers the way the case needs. A page
   that redrew the states by hand would be a second implementation and would drift. */

import { computed } from 'vue'

import AuditView from '@/views/AuditView.vue'
import ChartFrame from '@/components/ChartFrame.vue'
import ClockControl from '@/components/ClockControl.vue'
import DashboardView from '@/views/DashboardView.vue'
import StateCase from '@/dev/StateCase.vue'
import SubscriberView from '@/views/SubscriberView.vue'
import SubscribersView from '@/views/SubscribersView.vue'
import UsersView from '@/views/UsersView.vue'
import {
  audit,
  detail,
  events,
  health,
  me,
  NEVER,
  PLANS,
  REFUSED,
  roles,
  subscribers,
  users,
} from '@/dev/fixtures'

const AT_ZERO = {
  now: '2026-09-06T09:00:00Z',
  offsetSeconds: 0,
  isSandbox: true,
  daysLeft: 365,
}
const WOUND = { ...AT_ZERO, now: '2026-10-06T09:00:00Z', offsetSeconds: 2_592_000, daysLeft: 335 }

/** The four, in one order, everywhere on this page. Reading it is comparing like with like. */
const STATES = ['loading', 'error', 'empty', 'data'] as const

const answered = { health: () => Promise.resolve(health()), plans: () => Promise.resolve(PLANS) }

const table = computed(() => ({
  loading: { ...answered, subscribers: NEVER },
  error: { ...answered, subscribers: REFUSED },
  empty: { ...answered, subscribers: () => Promise.resolve(subscribers(0, 0)) },
  data: { ...answered, subscribers: () => Promise.resolve(subscribers(4, 351)) },
}))

const card = computed(() => ({
  loading: { ...answered, subscriber: NEVER, subscriberEvents: NEVER },
  error: { ...answered, subscriber: REFUSED, subscriberEvents: REFUSED },
  empty: {
    ...answered,
    subscriber: () => Promise.resolve(detail()),
    subscriberEvents: () => Promise.resolve(events(0, 0)),
  },
  data: {
    ...answered,
    subscriber: () => Promise.resolve(detail()),
    subscriberEvents: () => Promise.resolve(events(3, 3)),
  },
}))

const log = computed(() => ({
  loading: { ...answered, audit: NEVER },
  error: { ...answered, audit: REFUSED },
  empty: { ...answered, audit: () => Promise.resolve(audit(0)) },
  data: { ...answered, audit: () => Promise.resolve(audit(3)) },
}))

const operators = computed(() => ({
  loading: { users: NEVER, roles: NEVER, me: () => Promise.resolve(me()) },
  error: { users: REFUSED, roles: REFUSED, me: () => Promise.resolve(me()) },
  empty: {
    users: () => Promise.resolve(users(0)),
    roles: () => Promise.resolve(roles(0)),
    me: () => Promise.resolve(me()),
  },
  data: {
    users: () => Promise.resolve(users(2)),
    roles: () => Promise.resolve(roles(3)),
    me: () => Promise.resolve(me()),
  },
}))

const summary = computed(() => ({
  loading: { me: NEVER },
  error: { me: REFUSED },
  // The dashboard reads the session and nothing else, so its empty state is a session with no
  // permissions on it rather than an answer with no rows.
  empty: { me: () => Promise.resolve({ ...me(), permissions: [] }) },
  data: { me: () => Promise.resolve(me()) },
}))

const clock = computed(() => ({
  loading: { clock: NEVER },
  error: { clock: REFUSED },
  empty: { clock: () => Promise.resolve(AT_ZERO) },
  data: { clock: () => Promise.resolve(WOUND) },
}))

const CLOCK_NOTES: Record<string, string> = {
  empty: 'A world nobody has wound. There is no fourth state here: a clock is never empty.',
  data: 'Wound a month on, which is the line the base world never shows until somebody presses.',
}

const FIGURE = {
  question: 'What is in the base right now?',
  source: 'Standing now, from the engine',
  invitation: 'No subscription has been started in this world yet.',
  failure: 'The service failed to handle this request. Try again; quote request 4b21e0.',
}
</script>

<template>
  <main class="flex flex-col gap-8 p-6">
    <header class="flex max-w-reading flex-col gap-2">
      <h1 class="text-title text-text-primary">Four states, on purpose</h1>
      <p class="text-ui text-text-secondary">
        Every figure, table and feed in this panel has a loading state, an empty state, an error
        state and the data itself. Each case below is the real screen with a service behind it that
        answers the way the case needs, so what is on this page is what is on that one.
      </p>
      <p class="text-ui text-text-muted">
        This page exists in the development build only. It is not routed in production.
      </p>
    </header>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">The subscriber table</h2>
      <div class="grid gap-6 2xl:grid-cols-2">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :service="table[state]"
          class="min-w-0"
        >
          <SubscribersView />
        </StateCase>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">The subscriber card and its history</h2>
      <div class="grid gap-6 2xl:grid-cols-2">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :service="card[state]"
          class="min-w-0"
        >
          <SubscriberView />
        </StateCase>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">A figure</h2>
      <p class="max-w-reading text-ui text-text-secondary">
        All five analytics figures are this component with different numbers in it, so its four
        states are theirs.
      </p>
      <div class="grid gap-6 lg:grid-cols-2">
        <ChartFrame
          v-bind="FIGURE"
          label="loading"
          :pending="true"
          :failed="false"
          :empty="false"
          :busy="false"
        />
        <ChartFrame v-bind="FIGURE" :pending="false" :failed="true" :empty="false" :busy="false" />
        <ChartFrame v-bind="FIGURE" :pending="false" :failed="false" :empty="true" :busy="false" />
        <ChartFrame
          v-bind="FIGURE"
          :pending="false"
          :failed="false"
          :empty="false"
          :busy="false"
          answer="351 subscriptions"
        >
          <p class="h-chart-plot rounded-control bg-surface-2" />
        </ChartFrame>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">The audit</h2>
      <div class="grid gap-6 2xl:grid-cols-2">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :service="log[state]"
          class="min-w-0"
        >
          <AuditView />
        </StateCase>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">Operators and roles</h2>
      <div class="grid gap-6 2xl:grid-cols-2">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :service="operators[state]"
          class="min-w-0"
        >
          <UsersView />
        </StateCase>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">The dashboard</h2>
      <div class="grid gap-6 2xl:grid-cols-2">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :service="summary[state]"
          class="min-w-0"
        >
          <DashboardView />
        </StateCase>
      </div>
    </section>

    <section class="flex flex-col gap-4">
      <h2 class="text-heading text-text-primary">The time machine</h2>
      <p class="max-w-reading text-ui text-text-secondary">
        The signature element, at 240px because that is the column it lives in.
      </p>
      <div class="grid gap-6 lg:grid-cols-4">
        <StateCase
          v-for="state in STATES"
          :key="state"
          :label="state"
          :note="CLOCK_NOTES[state]"
          :service="clock[state]"
        >
          <div class="w-sidebar bg-surface-1 p-4"><ClockControl /></div>
        </StateCase>
      </div>
    </section>
  </main>
</template>
