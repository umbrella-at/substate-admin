/**
 * Five figures, five requests. A figure that failed says so where it is rather than blanking the
 * four beside it, and only the two that take a period refetch when the period changes.
 */

/* The period is in the query key for the reason the table's filters are in its: an answer is
   filed under the question that asked it, so a late one lands in a cache entry nobody reads. */

import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'

import type {
  FlowResponse,
  FunnelResponse,
  QuietResponse,
  RevenueResponse,
  StatesResponse,
} from '@/api/client'
import { useApiClient } from '@/api/provide'
import { periodParams, REVENUE_MONTHS, type Preset } from '@/domain/analytics'

/** Half a minute, which is the interval the world moves on. Asking faster than the world changes
 *  spends requests to redraw the same picture. */
const FRESH_FOR = 30_000

export function useAnalytics(period: Ref<Preset>, now: Ref<Date>) {
  const client = useApiClient()
  const params = computed(() => periodParams(period.value, now.value))
  const key = computed(() => period.value.value)

  const funnel = useQuery<FunnelResponse>({
    queryKey: computed(() => ['analytics', 'funnel', key.value]),
    queryFn: ({ signal }) => client.funnel(params.value, signal),
    placeholderData: keepPreviousData,
    staleTime: FRESH_FOR,
  })

  const flow = useQuery<FlowResponse>({
    queryKey: computed(() => ['analytics', 'flow', key.value]),
    queryFn: ({ signal }) => client.flow(params.value, signal),
    placeholderData: keepPreviousData,
    staleTime: FRESH_FOR,
  })

  const states = useQuery<StatesResponse>({
    queryKey: ['analytics', 'states'],
    queryFn: ({ signal }) => client.states(signal),
    staleTime: FRESH_FOR,
  })

  const quiet = useQuery<QuietResponse>({
    queryKey: ['analytics', 'quiet'],
    queryFn: ({ signal }) => client.quiet(signal),
    staleTime: FRESH_FOR,
  })

  const revenue = useQuery<RevenueResponse>({
    queryKey: ['analytics', 'revenue'],
    queryFn: ({ signal }) => {
      const months = new URLSearchParams({ months: String(REVENUE_MONTHS) })
      return client.revenue(months, signal)
    },
    staleTime: FRESH_FOR,
  })

  return { funnel, flow, states, quiet, revenue }
}
