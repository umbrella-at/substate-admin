/**
 * The table's data, and the guarantee that the answer on screen belongs to the question on screen.
 *
 * Filters change faster than the network answers. A visitor who ticks "grace" and then "trial"
 * has two requests in flight, and nothing about the order they were sent decides the order they
 * come back — so the naive version shows the grace page under a trial filter, and the only clue
 * is that the numbers look wrong to somebody who already knows what to expect.
 *
 * Two mechanisms, and it is worth being clear that they are different. The query key is the
 * question: an answer is filed under the question that asked it, so a late one lands in a cache
 * entry nobody is reading rather than on screen. The abort signal is the courtesy: the request
 * that stopped mattering is cancelled instead of being paid for. Correctness comes from the
 * first; the second keeps a fast typist from opening a dozen sockets.
 *
 * `keepPreviousData` is what makes paging feel like paging. Without it every page change empties
 * the table to a skeleton and the rows jump; with it the previous page stays under a dimmed
 * overlay until the next one lands, which is also the honest picture — those rows are real, they
 * are simply one question out of date.
 */

import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'

import type { SubscriberPage } from '@/api/client'
import { useApiClient } from '@/api/provide'
import { queryKey, queryToSearchParams, type SubscriberQuery } from '@/domain/subscribers'

export function useSubscribers(query: Ref<SubscriberQuery>) {
  const client = useApiClient()

  const result = useQuery<SubscriberPage>({
    queryKey: computed(() => ['subscribers', queryKey(query.value)]),
    queryFn: ({ signal }) => client.subscribers(queryToSearchParams(query.value), signal),
    placeholderData: keepPreviousData,
  })

  const total = computed(() => result.data.value?.total ?? 0)
  const pageCount = computed(() =>
    total.value === 0 ? 0 : Math.ceil(total.value / query.value.pageSize),
  )

  return {
    ...result,
    rows: computed(() => result.data.value?.items ?? []),
    total,
    pageCount,
    // Distinct from `isPending`, which is only true when there is nothing to show at all. This is
    // the state where real rows are on screen and a newer answer is on its way.
    isRefreshing: computed(() => result.isFetching.value && !result.isPending.value),
  }
}
