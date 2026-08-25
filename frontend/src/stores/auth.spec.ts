/**
 * The opening exchange, and the one thing about it that is easy to get backwards.
 *
 * A 401 during bootstrap is not a failure. It is the ordinary, expected answer for a visitor who
 * has never signed in — every first visit to this application produces one — and a store that
 * reported it as an error would put an error banner in front of the login form on a page that has
 * not done anything wrong yet.
 *
 * The other assertion here is about `ready`. The router guard waits on it, so a path that leaves
 * it false is a navigation that never resolves: a blank page, no error, nothing in the console.
 * Every path through `bootstrap` is checked for it, including the one that ends in a throw.
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient, type MeResponse } from '@/api/client'

import { useAuthStore } from './auth'

const ME: MeResponse = {
  kind: 'user',
  permissions: ['users.read', 'audit.read'],
  role: { code: 'support', name: 'Support' },
  user: {
    createdAt: '2026-01-01T00:00:00Z',
    email: 'operator@example.com',
    id: '00000000-0000-0000-0000-000000000000',
    isActive: true,
    lastLoginAt: '2026-08-25T09:00:00Z',
  },
}

/** Only the two methods `bootstrap` uses. The store is deliberately handed a client rather than
 *  importing one, which is what makes this possible without a fake server. */
function stubClient(parts: Partial<ApiClient>): ApiClient {
  return parts as ApiClient
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('bootstrap', () => {
  it('adopts the session when the opening refresh survives', async () => {
    const me = vi.fn<() => Promise<MeResponse>>().mockResolvedValue(ME)
    const auth = useAuthStore()

    await auth.bootstrap(stubClient({ refresh: async () => 'renewed' as const, me }))

    expect(me).toHaveBeenCalledTimes(1)
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.user?.email).toBe('operator@example.com')
    expect(auth.role?.code).toBe('support')
    expect(auth.kind).toBe('user')
    expect([...auth.permissions]).toEqual(['users.read', 'audit.read'])
    expect(auth.ready).toBe(true)
  })

  it('leaves a first-time visitor anonymous without throwing', async () => {
    // What a 401 from `/auth/refresh` looks like by the time it reaches here: the client answers
    // false rather than raising, because a person who has never signed in is not an exception.
    const me = vi.fn<() => Promise<MeResponse>>()
    const auth = useAuthStore()

    await expect(
      auth.bootstrap(stubClient({ refresh: async () => 'refused' as const, me })),
    ).resolves.toBeUndefined()

    expect(me).not.toHaveBeenCalled()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.ready).toBe(true)
  })

  it('stays anonymous, quietly, when the session is refused at /auth/me', async () => {
    const auth = useAuthStore()
    const me = vi
      .fn<() => Promise<MeResponse>>()
      .mockRejectedValue(new ApiError(401, { code: 'NOT_AUTHENTICATED', message: 'No session.' }))

    await expect(
      auth.bootstrap(stubClient({ refresh: async () => 'renewed' as const, me })),
    ).resolves.toBeUndefined()

    expect(auth.isAuthenticated).toBe(false)
    expect([...auth.permissions]).toEqual([])
    expect(auth.ready).toBe(true)
  })

  it('does not leave a stale session standing when a later bootstrap is refused', async () => {
    // The tab that was signed in, was left open, and is reloaded after the session died. Adopting
    // nothing is not enough: whatever the store already holds has to go, or the guard keeps
    // letting a ghost through.
    const auth = useAuthStore()
    auth.adopt(ME)
    expect(auth.isAuthenticated).toBe(true)

    await auth.bootstrap(
      stubClient({
        refresh: async () => 'renewed' as const,
        me: async () => {
          throw new ApiError(401, { code: 'TOKEN_EXPIRED', message: 'Expired.' })
        },
      }),
    )

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.role).toBeNull()
    expect([...auth.permissions]).toEqual([])
  })

  it('mounts anonymous rather than escaping when the failure is not the server refusing', async () => {
    // The outcome this replaces used to be a rethrow, and main.ts awaits bootstrap at module
    // scope with nothing to catch it — so a connection dropping between the refresh answering and
    // `me()` going out left the page as an empty div forever: no message, no spinner, nothing to
    // click, and only an unhandled rejection in a console nobody has open. Anonymous is the only
    // thing a pre-mount failure can mean.
    const auth = useAuthStore()

    await expect(
      auth.bootstrap(
        stubClient({
          refresh: async () => 'renewed' as const,
          me: async () => {
            throw new TypeError('Failed to fetch')
          },
        }),
      ),
    ).resolves.toBeUndefined()

    expect(auth.ready).toBe(true)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('gives up after five seconds and mounts anonymous', async () => {
    // The API runs as exactly one uvicorn worker, so a single stuck request stalls the process.
    // Without the deadline the top-level await in main.ts never settles and the page never
    // appears at all — the worst available outcome, and the hardest to diagnose.
    vi.useFakeTimers()
    try {
      const auth = useAuthStore()
      const pending = auth.bootstrap(
        stubClient({ refresh: () => new Promise(() => {}), me: async () => ME }),
      )
      await vi.advanceTimersByTimeAsync(5_000)
      await expect(pending).resolves.toBeUndefined()
      expect(auth.ready).toBe(true)
      expect(auth.isAuthenticated).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('the session it holds', () => {
  it('answers can() from the granted set and from nothing else', () => {
    const auth = useAuthStore()
    auth.adopt(ME)

    expect(auth.can('users.read')).toBe(true)
    expect(auth.can('audit.read')).toBe(true)
    // Held for the sibling code, and that grants nothing: read is not write.
    expect(auth.can('users.write')).toBe(false)
    expect(auth.can('subscribers.read')).toBe(false)
  })

  it('empties every part of the session on clear, permissions included', () => {
    // The permissions set is the one that matters. A cleared user with a populated set is a store
    // that answers "no" to isAuthenticated and "yes" to can(), and the second question is the one
    // a menu asks.
    const auth = useAuthStore()
    auth.adopt(ME)

    auth.clear()

    expect(auth.user).toBeNull()
    expect(auth.role).toBeNull()
    expect(auth.kind).toBeNull()
    expect([...auth.permissions]).toEqual([])
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.can('users.read')).toBe(false)
    // Not part of the session: clearing is what happens when one ends, and the opening exchange
    // has still been answered.
    expect(auth.ready).toBe(false)
  })

  it('replaces the permissions of the previous session rather than adding to them', () => {
    const auth = useAuthStore()
    auth.adopt(ME)
    auth.adopt({ ...ME, permissions: ['plans.read'], role: { code: 'viewer', name: 'Viewer' } })

    expect([...auth.permissions]).toEqual(['plans.read'])
    expect(auth.can('users.read')).toBe(false)
    expect(auth.role?.code).toBe('viewer')
  })
})
