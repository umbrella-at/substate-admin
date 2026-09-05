/**
 * Ending a session, in one place.
 *
 * There are two ways a session ends and they must not diverge: the person presses `Sign out`, or
 * the server stops accepting the refresh cookie. If those were written separately, one of them
 * would eventually forget a step — and the step it would forget is the cache.
 *
 * `queryClient.clear()` is the reason this file exists. TanStack Query's cache is keyed by query,
 * not by person. Sign out on a shared machine without clearing it and the next person to sign in
 * sees the previous one's data rendered from cache while their own request is still in flight:
 * every guarantee the backend makes about permissions, defeated on the client by a stale key.
 */

import type { QueryClient } from '@tanstack/vue-query'

import type { ApiClient } from '@/api/client'
import { forgetWorldClock } from '@/composables/useWorldClock'
import { useAuthStore } from '@/stores/auth'

/** Drop every trace of the current session from this tab. Local only: it makes no requests, so it
 *  cannot fail, which is what lets both callers below run it unconditionally. */
export function forgetSession(client: ApiClient, queryClient: QueryClient): void {
  useAuthStore().clear()
  client.setAccessToken(null)
  queryClient.clear()
  // The world goes with the session. A demonstration wound a month forward leaves an offset that
  // would otherwise date every row on the first screen of whoever signs in next.
  forgetWorldClock()
}

/** The explicit `Sign out`. Tells the server first so the refresh family is revoked rather than
 *  merely abandoned, then forgets the session locally whatever the server answered.
 *
 *  The `catch` is deliberate and not laziness: if the network is down, refusing to sign out would
 *  leave someone stuck signed in on a machine they are walking away from. The local half always
 *  happens; the worst case is a refresh token that stays valid until it expires on its own. */
export async function signOut(client: ApiClient, queryClient: QueryClient): Promise<void> {
  try {
    await client.logout()
  } catch {
    // Nothing to report: the outcome for this tab is identical either way.
  } finally {
    forgetSession(client, queryClient)
  }
}
