/**
 * One subscriber's card, its feed, and the operations that change both.
 *
 * WHAT AN OPERATION DOES TO THE CACHE, AND WHY IT IS NOT A REFETCH. The answer to an operation is
 * the card as the engine now holds it, so it is written straight into the cache: a refetch would
 * be a second round trip to ask a question the answer already contains, and the card would flicker
 * through its old state on the way.
 *
 * The feed IS refetched, and that is not an inconsistency. The answer carries what this call
 * emitted, not the rows those events were written as — and the feed is a page of the journal,
 * which the thirty-second ticker also writes to. Asking again is the only way to get the page that
 * is now true rather than the page that would be true if nothing else had happened.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, type Ref } from 'vue'

import type {
  OperationPath,
  SubscriberDetail,
  SubscriberEventPage,
  SubscriberOperationResult,
} from '@/api/client'
import { useApiClient } from '@/api/provide'

export const FEED_PAGE_SIZE = 25

export function useSubscriber(userId: Ref<string>) {
  const client = useApiClient()

  return useQuery<SubscriberDetail>({
    queryKey: computed(() => ['subscriber', userId.value]),
    queryFn: ({ signal }) => client.subscriber(userId.value, signal),
  })
}

export function useSubscriberEvents(userId: Ref<string>, page: Ref<number>) {
  const client = useApiClient()

  const result = useQuery<SubscriberEventPage>({
    queryKey: computed(() => ['subscriber-events', userId.value, page.value]),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        page: String(page.value),
        pageSize: String(FEED_PAGE_SIZE),
      })
      return client.subscriberEvents(userId.value, params, signal)
    },
    // The rows under a card should not empty to a skeleton when the pager moves: they are real,
    // they are one page out of date, and dimming them says so more honestly than removing them.
    placeholderData: keepPreviousData,
  })

  const total = computed(() => result.data.value?.total ?? 0)

  return {
    ...result,
    rows: computed(() => result.data.value?.items ?? []),
    total,
    pageCount: computed(() => (total.value === 0 ? 0 : Math.ceil(total.value / FEED_PAGE_SIZE))),
    isRefreshing: computed(() => result.isFetching.value && !result.isPending.value),
  }
}

export interface OperationRequest {
  operation: OperationPath
  body?: unknown
}

/**
 * The one mutation behind all six controls.
 *
 * There is no optimistic update and there will not be one. Three of the payment outcomes are
 * successes that change nothing — a duplicate reference, a short payment, a payment against a
 * cancelled record — so a card written before the answer arrives would show a renewal that did not
 * happen and then take it back. The engine is the only thing that knows which of the five
 * happened, and it says so in the events it returns.
 */
export function useSubscriberOperation(userId: Ref<string>) {
  const client = useApiClient()
  const cache = useQueryClient()

  return useMutation<SubscriberOperationResult, Error, OperationRequest>({
    mutationFn: ({ operation, body }) => client.operate(userId.value, operation, body),
    onSuccess: (result) => {
      cache.setQueryData(['subscriber', userId.value], result.subscriber)
      void cache.invalidateQueries({ queryKey: ['subscriber-events', userId.value] })
      // The table behind the card is now one state out of date, and so is the audit.
      void cache.invalidateQueries({ queryKey: ['subscribers'] })
      void cache.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}
