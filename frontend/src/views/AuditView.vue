<script setup lang="ts">
/**
 * What operators did.
 *
 * ATTEMPTS, NOT SUCCESSES. A refused operation is a row, and it is the row an investigation is
 * most likely to want: a log of what worked cannot tell somebody who cancelled one subscription
 * from somebody who tried nine and succeeded once. The objection — that refusals are noise — is
 * answered by the filter, which is one control away and defaults to showing everything.
 *
 * A ROW OUTLIVES THE WORLD IT NAMES. The base world is rebuilt when the service restarts, so a row
 * from before the last restart refers to a subscriber whose state has been reset. The subscriber
 * cell is a link only when the row's world is the one this panel is looking at; otherwise it is
 * plain text, because a link that 404s is worse than a word that does not offer.
 *
 * The address of this screen is its state, like the table's — a page of the audit narrowed to one
 * subscriber is a thing somebody sends to a colleague.
 */

import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, type AuditPage } from '@/api/client'
import { useApiClient } from '@/api/provide'
import AppButton from '@/components/AppButton.vue'
import AppNotice from '@/components/AppNotice.vue'
import AuditTable from '@/components/AuditTable.vue'
import SkeletonBlock from '@/components/SkeletonBlock.vue'
import TablePager from '@/components/TablePager.vue'
import { Checkbox } from '@/components/ui/checkbox'
import {
  ACTION_LABEL,
  AUDIT_ACTIONS,
  auditQueryFromRoute,
  auditQueryKey,
  auditQueryToRoute,
  auditQueryToSearchParams,
  EMPTY_AUDIT_QUERY,
  hasAuditFilters,
  type AuditQuery,
  type Outcome,
} from '@/domain/audit'
import { useWorld } from '@/composables/useWorld'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const client = useApiClient()
const auth = useAuthStore()

const query = computed<AuditQuery>(() => auditQueryFromRoute(route.query))

const result = useQuery<AuditPage>({
  queryKey: computed(() => ['audit', auditQueryKey(query.value)]),
  queryFn: ({ signal }) => client.audit(auditQueryToSearchParams(query.value), signal),
})

const rows = computed(() => result.data.value?.items ?? [])
const total = computed(() => result.data.value?.total ?? 0)
const pageSize = computed(() => result.data.value?.pageSize ?? 25)
const pageCount = computed(() => (total.value === 0 ? 0 : Math.ceil(total.value / pageSize.value)))

/** Which world the panel is looking at. A row from another one points at a subscriber who was
 *  reset away, so its target is text rather than a link. */

/* THE SESSION'S OWN WORLD FIRST, AND THAT IS WHAT SANDBOXES CHANGED. `/api/health` is public and
   always names the base world, so a demonstration visitor asking it would be told their own rows
   belong to somewhere else — and every link on their audit screen would quietly stop existing. */

/* Null while neither answer has arrived, which the table reads as "do not link". That is the
   right way round: an unlinked id is readable, and a link built on a guess is a 404. */
const { data: health } = useWorld()
const liveWorld = computed(() => auth.worldId ?? health.value?.world.id ?? null)

function go(next: AuditQuery): void {
  void router.push({ query: auditQueryToRoute(next) })
}

function toggleAction(action: (typeof AUDIT_ACTIONS)[number], on: boolean): void {
  const actions = on
    ? [...query.value.actions, action]
    : query.value.actions.filter((each) => each !== action)
  go({ ...query.value, page: 1, actions })
}

function setOutcome(outcome: Outcome | null): void {
  go({ ...query.value, page: 1, outcome })
}

const UNREACHABLE = 'The service could not be reached.'
const failure = computed(() => {
  const cause = result.error.value
  if (cause instanceof ApiError && cause.status < 500 && cause.message !== '') return cause.message
  return UNREACHABLE
})
</script>

<template>
  <section class="flex flex-col gap-6 p-6">
    <header class="flex flex-col gap-2">
      <h1 class="text-title text-text-primary">Audit</h1>
      <p class="max-w-reading text-ui text-text-secondary">
        Every operation an administrator attempted, whether or not the engine accepted it. Signing
        in and changing a filter are not here — those are in the service's own logs.
      </p>
    </header>

    <div class="flex flex-col gap-4 rounded-panel bg-surface-1 p-4">
      <fieldset class="flex flex-wrap items-center gap-x-4 gap-y-2">
        <legend class="sr-only">Action</legend>
        <span class="text-caption text-text-secondary" aria-hidden="true">Action</span>
        <label
          v-for="action in AUDIT_ACTIONS"
          :key="action"
          class="flex items-center gap-2 text-ui text-text-secondary"
        >
          <Checkbox
            :model-value="query.actions.includes(action)"
            @update:model-value="
              (on: boolean | 'indeterminate') => toggleAction(action, on === true)
            "
          />
          {{ ACTION_LABEL[action] }}
        </label>
      </fieldset>

      <fieldset class="flex flex-wrap items-center gap-x-4 gap-y-2">
        <legend class="sr-only">Outcome</legend>
        <span class="text-caption text-text-secondary" aria-hidden="true">Outcome</span>
        <AppButton
          v-for="choice in [null, 'ok', 'refused'] as const"
          :key="String(choice)"
          :variant="query.outcome === choice ? 'outlined' : 'plain'"
          :aria-pressed="query.outcome === choice"
          @click="setOutcome(choice)"
        >
          {{ choice === null ? 'Everything' : choice === 'ok' ? 'Accepted' : 'Refused' }}
        </AppButton>
      </fieldset>

      <!-- The two narrowings that have no control of their own: both are set by clicking a cell
           in the table, so both need a way back that does not depend on the result being empty.
           They were only clearable from the empty state, which is the one place a person who had
           found what they were looking for never reaches. -->
      <div
        v-if="hasAuditFilters(query)"
        class="flex flex-wrap items-center gap-x-4 gap-y-2 text-dense text-text-muted"
      >
        <span v-if="query.targetId !== null">
          Narrowed to <span class="font-numeric">{{ query.targetId }}</span>
        </span>
        <span v-if="query.actorUserId !== null">Narrowed to one operator</span>
        <AppButton variant="outlined" @click="go(EMPTY_AUDIT_QUERY)">Clear filters</AppButton>
      </div>
    </div>

    <div v-if="result.isPending.value" class="flex flex-col gap-4" aria-busy="true">
      <span class="sr-only">Loading the audit</span>
      <div class="overflow-hidden rounded-panel border border-border">
        <SkeletonBlock v-for="line in 5" :key="line" class="m-4 h-8" />
      </div>
    </div>

    <div v-else-if="result.isError.value" class="flex flex-col items-start gap-4">
      <AppNotice role="danger" assertive>{{ failure }}</AppNotice>
      <AppButton variant="outlined" @click="() => void result.refetch()">Try again</AppButton>
    </div>

    <template v-else>
      <AuditTable
        :rows="rows"
        :live-world="liveWorld"
        :busy="result.isFetching.value"
        @filter-actor="(id: string) => go({ ...query, page: 1, actorUserId: id })"
        @filter-target="(id: string) => go({ ...query, page: 1, targetId: id })"
      />

      <div v-if="rows.length === 0" class="flex flex-col items-start gap-3 py-8">
        <p class="max-w-reading text-ui text-text-secondary">
          {{
            hasAuditFilters(query)
              ? 'No recorded action matches these filters.'
              : 'Nothing has been done to a subscription yet. Open a subscriber and perform an operation, and it will be recorded here.'
          }}
        </p>
        <AppButton v-if="hasAuditFilters(query)" variant="outlined" @click="go(EMPTY_AUDIT_QUERY)">
          Clear filters
        </AppButton>
      </div>

      <TablePager
        :page="query.page"
        :page-count="pageCount"
        :total="total"
        :busy="result.isFetching.value"
        noun="recorded action"
        plural="recorded actions"
        @go="(page: number) => go({ ...query, page })"
      />
    </template>
  </section>
</template>
