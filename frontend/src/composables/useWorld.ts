/**
 * Whether the demonstration has a world behind it.
 *
 * The panel is a shop window over a world the service builds at start-up by running nine months
 * of subscriptions through `substate`. That run is wrapped so it cannot take the service down with
 * it — signing in, permissions and every operator screen keep working without it — which means the
 * failure it produces is a panel that looks finished and empty rather than a panel that is broken.
 * `/api/health` has carried `world.seeded` since the world existed; nothing on this side asked.
 *
 * IN QUERY, NOT IN PINIA. It is a fact about the server that this client can only ever read, go
 * stale on, and re-ask for. The store holds what the session knows about itself; this is somebody
 * else's state, and putting it there would mean writing by hand the refetching, the staleness and
 * the request de-duplication that the query cache already does.
 */

import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import type { HealthResponse } from '@/api/client'
import { useApiClient } from '@/api/provide'

/** Half a minute. The world is rebuilt when the service restarts, so the answer changes rarely and
 *  only for a reason a visitor cannot cause — but it does change, and a page left open across a
 *  deploy should not go on describing the world it had when it loaded. */
const FRESH_FOR = 30_000

export function useWorld() {
  const client = useApiClient()

  const query = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: ({ signal }) => client.health(signal),
    staleTime: FRESH_FOR,
  })

  return {
    ...query,
    /** True only when the service has answered and said so.
     *
     *  Written as `=== false` rather than as a negated optimistic default, because the three
     *  states are not two: built, not built, and not yet known. A health request that is still in
     *  flight or has failed outright must not put "the world was not built" on screen — that is a
     *  claim, and the only evidence for it is an answer that makes it.
     */
    isUnbuilt: computed(() => query.data.value?.world.seeded === false),
  }
}
