<script setup lang="ts">
/**
 * The route is the only state: filters, sort and page are read out of it and written back, and
 * nothing here keeps a second copy. A control that edited its own state and then told the router
 * would have two to keep in step, and the back button is what pulls them apart.
 */

import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'

import { ApiError, type PlanSummary } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import SubscribersFilters from '@/components/SubscribersFilters.vue'
import SubscribersTable from '@/components/SubscribersTable.vue'
import WorldNotBuilt from '@/components/WorldNotBuilt.vue'
import TablePager from '@/components/TablePager.vue'
import { useSubscribers } from '@/composables/useSubscribers'
import { useWorld } from '@/composables/useWorld'
import {
  EMPTY_QUERY,
  queryFromRoute,
  queryToRoute,
  type SortField,
  type SubscriberQuery,
} from '@/domain/subscribers'

const route = useRoute()
const router = useRouter()
const client = useApiClient()

const query = computed<SubscriberQuery>(() => queryFromRoute(route.query))

const { rows, total, pageCount, isPending, isError, error, isRefreshing, refetch } =
  useSubscribers(query)

/** Asked once for the whole screen. An empty page of subscribers means two entirely different
 *  things depending on the answer, and only one of them is a table with nothing in it. */
const { isUnbuilt: worldIsUnbuilt } = useWorld()

/** The catalogue for the plan filter. Separate from the table's own request because it does not
 *  change when the filters do, and refetching five unchanging rows on every keystroke would be
 *  work with no result. */
const { data: plans } = useQuery<PlanSummary[]>({
  queryKey: ['plans'],
  queryFn: ({ signal }) => client.plans(signal),
  staleTime: Infinity,
})

const planIds = computed(() => (plans.value ?? []).map((plan) => plan.id))

/** A question the visitor asked deliberately becomes a history entry; one that is still being
 *  typed replaces the last. Either way the address is the only state, and this is the only place
 *  that writes it. */
function go(next: SubscriberQuery, options: { replace: boolean } = { replace: false }): void {
  const to = { query: queryToRoute(next) }
  void (options.replace ? router.replace(to) : router.push(to))
}

/** Where a header click leads. A first click sorts ascending, a second reverses it, and a third
 *  does not clear it — an unsorted table is not a thing anybody navigates to on purpose, and
 *  cycling through it means one click in three appears to do nothing. */
function sortHref(field: SortField): RouteLocationRaw {
  const current = query.value.sort
  const descending = current !== null && current.field === field && !current.descending
  return {
    query: queryToRoute({
      ...query.value,
      page: 1,
      sort: { field, descending },
    }),
  }
}

const hasFilters = computed(
  () =>
    query.value.states.length > 0 ||
    query.value.cohort !== null ||
    query.value.planIds.length > 0 ||
    query.value.q !== null,
)

const UNREACHABLE = 'The service could not be reached.'

const failure = computed(() => {
  const cause = error.value
  if (cause instanceof ApiError && cause.status < 500 && cause.message !== '') return cause.message
  return UNREACHABLE
})
</script>

<template>
  <section class="flex flex-col gap-6 p-6">
    <header class="flex flex-col gap-2">
      <h1 class="text-title text-text-primary">Subscribers</h1>
      <!-- The sentence describes what is in the table. With no world there is no table, and a
           description of absent contents is the screen claiming something it cannot show. -->
      <p v-if="!worldIsUnbuilt" class="max-w-reading text-ui text-text-secondary">
        Everyone in the world this panel is looking at, with the state
        <code class="font-numeric">substate</code> holds for them right now.
      </p>
    </header>

    <!-- Hidden with no world: filters over nothing answer every use with the same emptiness.
         The 24px to the table is this section's `gap-6` — an `mb-6` here as well makes it 48. -->
    <SubscribersFilters v-if="!worldIsUnbuilt" :query="query" :plans="planIds" @change="go" />

    <!-- Loading, with nothing to show. The skeleton is the shape of the table rather than a
         spinner: five rows of the same height, so the page does not resize when they arrive. -->
    <div v-if="isPending" class="flex flex-col gap-4" aria-busy="true">
      <span class="sr-only">Loading subscribers</span>
      <div class="overflow-hidden rounded-panel border border-border">
        <SkeletonBlock v-for="row in 5" :key="row" class="m-4 h-8" />
      </div>
    </div>

    <!-- Failed. The retry is here because the usual cause is the network, and the usual fix is
         asking again — sending somebody to reload the page would throw away their filters. -->
    <div v-else-if="isError" class="flex flex-col items-start gap-4">
      <AppNotice role="danger" assertive>{{ failure }}</AppNotice>
      <AppButton variant="outlined" @click="() => void refetch()">Try again</AppButton>
    </div>

    <!-- Not the empty state: the request succeeded, and there is nothing because the run that
         builds the world did not finish. As ordinary emptiness this reads as a finished panel. -->
    <WorldNotBuilt v-else-if="worldIsUnbuilt" />

    <template v-else>
      <div class="flex flex-col gap-4">
        <!-- The dim is on the table alone, and the filters stay live underneath it: the point of
             keeping the old rows is that the screen still works while the new ones arrive. -->
        <div :class="isRefreshing ? 'opacity-60 transition-opacity' : ''">
          <SubscribersTable
            :rows="rows"
            :sort="query.sort"
            :sort-href="sortHref"
            :busy="isRefreshing"
          />
        </div>

        <div v-if="rows.length === 0" class="flex flex-col items-start gap-3 py-8">
          <p class="text-ui text-text-secondary">
            {{
              hasFilters
                ? 'No subscribers match these filters.'
                : 'This world has no subscribers yet.'
            }}
          </p>
          <AppButton
            v-if="hasFilters"
            variant="outlined"
            @click="go({ ...EMPTY_QUERY, pageSize: query.pageSize })"
          >
            Clear filters
          </AppButton>
        </div>

        <TablePager
          :page="query.page"
          :page-count="pageCount"
          :total="total"
          :busy="isRefreshing"
          @go="(page: number) => go({ ...query, page })"
        />
      </div>
    </template>
  </section>
</template>
