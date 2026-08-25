/**
 * The only Pinia store in the project, and the specification says so: caching, invalidation,
 * retries and request state are TanStack Query's work, and writing them by hand in a store is how
 * you end up with a worse Query. What lives here is the session — who is signed in and what they
 * may do — which is client state by nature.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { ApiClient, MeResponse } from '@/api/client'
import type { PermissionCode } from '@/domain/permissions'

export type SessionUser = MeResponse['user']
export type SessionRole = MeResponse['role']

/** Five seconds, from the specification. Long enough for a slow connection, short enough that a
 *  person does not sit in front of an empty page wondering whether it is broken. */
const BOOTSTRAP_TIMEOUT_MS = 5_000

export const useAuthStore = defineStore('auth', () => {
  const user = ref<SessionUser | null>(null)
  const role = ref<SessionRole | null>(null)
  const permissions = ref<ReadonlySet<string>>(new Set())
  const kind = ref<MeResponse['kind'] | null>(null)

  /** False until the opening refresh has been answered one way or the other. The router guard
   *  waits on it; without that wait the first navigation of a reload reads an empty store and
   *  sends a signed-in person to the login page. */
  const ready = ref(false)

  const isAuthenticated = computed(() => user.value !== null)

  function can(permission: PermissionCode): boolean {
    return permissions.value.has(permission)
  }

  function adopt(me: MeResponse): void {
    user.value = me.user
    role.value = me.role
    kind.value = me.kind
    permissions.value = new Set(me.permissions)
  }

  function clear(): void {
    user.value = null
    role.value = null
    kind.value = null
    permissions.value = new Set()
  }

  /** The opening exchange, run once before the application is mounted.
   *
   *  Every path through this function ends the same way: mounted, and either signed in or not.
   *  There is no failure mode where it is correct to leave the page unmounted, because an
   *  unmounted page is a blank rectangle with no message, no spinner and nothing to click — the
   *  worst outcome available, and the one that used to happen when a connection dropped between
   *  the refresh answering and `me()` going out.
   *
   *  A 401 here is the ordinary answer for a visitor who has never signed in. It is not an error
   *  and must not be reported as one.
   *
   *  The deadline matters more than it looks: the API runs as exactly one uvicorn worker, so a
   *  single stuck request stalls the process, and without a timeout the top-level await in
   *  main.ts would never settle and the page would never appear at all. */
  async function bootstrap(client: ApiClient, timeoutMs = BOOTSTRAP_TIMEOUT_MS): Promise<void> {
    try {
      const outcome = await Promise.race([
        client.refresh(),
        new Promise<'undeliverable'>((resolve) => {
          setTimeout(() => resolve('undeliverable'), timeoutMs)
        }),
      ])
      if (outcome === 'renewed') adopt(await client.me())
      else clear()
    } catch {
      // Anonymous is the only thing a pre-mount failure can mean, whatever kind of failure it was.
      clear()
    } finally {
      ready.value = true
    }
  }

  return { user, role, permissions, kind, ready, isAuthenticated, can, adopt, clear, bootstrap }
})
