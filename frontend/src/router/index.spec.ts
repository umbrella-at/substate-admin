/**
 * The guard, exercised through the real router rather than by calling the callback by hand.
 *
 * Two of these tests are the ones that would be embarrassing to be missing. The first is
 * default-closed: a route added without any `meta` at all must be protected, because the way this
 * rule fails in practice is not an argument about defaults, it is somebody adding a page in a
 * hurry. The second is `next`: it is attacker-supplied text arriving on the one page in the
 * application that asks for a password, and a login form that forwards to whatever it was handed
 * is an open redirect with a credential prompt in front of it.
 *
 * The routes below are added to the live router so that they go through the same `beforeEach` the
 * real ones do. A guard tested through a copy of itself is a guard nobody has tested.
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { h } from 'vue'

import { ApiError, type ApiClient, type MeResponse } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

import { provideApiClient, router, safeNext } from './index'

const Blank = { render: () => h('div') }

function session(permissions: string[]): MeResponse {
  return {
    kind: 'user',
    permissions,
    role: { code: 'support', name: 'Support' },
    user: {
      createdAt: '2026-01-01T00:00:00Z',
      email: 'operator@example.com',
      id: '00000000-0000-0000-0000-000000000000',
      isActive: true,
      lastLoginAt: null,
    },
  }
}

/** The client the guard bootstraps with. `null` is a visitor with no session, which is exactly
 *  what the real client reports: `refresh()` answers 'refused' rather than raising. */
function clientFor(me: MeResponse | null, delayMs = 0): ApiClient {
  return {
    refresh: async () => {
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs))
      return me !== null ? ('renewed' as const) : ('refused' as const)
    },
    me: async () => {
      if (me === null)
        throw new ApiError(401, { code: 'NOT_AUTHENTICATED', message: 'No session.' })
      return me
    },
  } as Partial<ApiClient> as ApiClient
}

// One route the application does not have, and it exists to test a rule rather than a page:
// `reports` deliberately declares no `meta` whatsoever, which is the whole point of it.
//
// `/audit` used to be added here too and is not any more. It is a real route now, and re-adding it
// replaced the application's own declaration with this file's copy — so the spec would have gone
// on passing if the real route lost its permission.
router.addRoute({ path: '/reports', name: 'reports', component: Blank })

let nonce = 0

/** Park the router somewhere public and unique before each test.
 *
 *  Unique because vue-router answers a navigation to the address it is already on with a
 *  duplicated-navigation failure and never runs the guard — which would quietly turn a test into
 *  an assertion about the previous test's state. */
async function park(): Promise<void> {
  setActivePinia(createPinia())
  provideApiClient(clientFor(null))
  nonce += 1
  await router.replace(`/login?reset=${nonce}`)
}

beforeEach(async () => {
  await park()
  // A fresh store for the test itself, so the guard runs its opening bootstrap against whatever
  // client the test is about to provide — the same order a browser reload produces.
  setActivePinia(createPinia())
})

describe('default closed', () => {
  it('protects a route that says nothing about authentication at all', async () => {
    provideApiClient(clientFor(null))

    await router.replace('/reports')

    const now = router.currentRoute.value
    expect(now.name).toBe('login')
    expect(now.query['next']).toBe('/reports')
  })

  it('keeps the whole address, query and all, so signing in returns where they were', async () => {
    provideApiClient(clientFor(null))

    await router.replace('/reports?tab=open&page=2')

    expect(router.currentRoute.value.query['next']).toBe('/reports?tab=open&page=2')
  })

  it('lets a stranger see the pages that say they are public', async () => {
    provideApiClient(clientFor(null))

    await router.replace('/nothing-is-here')

    // Not-found is public on purpose: bouncing an anonymous visitor to the login page over a typo
    // would tell them the address exists.
    expect(router.currentRoute.value.name).toBe('not-found')
  })
})

describe('someone already signed in', () => {
  it('is sent onward from the login page rather than shown it again', async () => {
    provideApiClient(clientFor(session(['audit.read'])))

    await router.replace('/login?next=/reports')

    expect(router.currentRoute.value.path).toBe('/reports')
  })

  it('lands on the dashboard when there is nowhere in particular to go', async () => {
    provideApiClient(clientFor(session([])))

    await router.replace('/login')

    expect(router.currentRoute.value.path).toBe('/')
  })

  it('is not forwarded off this site by a next it was handed', async () => {
    for (const hostile of ['//evil.example', 'https://evil.example', 'javascript:alert(1)']) {
      await park()
      setActivePinia(createPinia())
      provideApiClient(clientFor(session([])))

      await router.replace({ path: '/login', query: { next: hostile } })

      expect(router.currentRoute.value.path).toBe('/')
    }
  })

  it('waits for the opening exchange instead of reading an empty store', async () => {
    // The bug this prevents looks exactly like "the session did not survive a reload": the first
    // navigation runs before the refresh has answered, finds nobody signed in, and redirects.
    provideApiClient(clientFor(session(['audit.read']), 5))

    await router.replace('/')

    expect(router.currentRoute.value.path).toBe('/')
    expect(useAuthStore().ready).toBe(true)
    expect(useAuthStore().isAuthenticated).toBe(true)
  })
})

describe('a permission the visitor does not hold', () => {
  it('answers at the address that was asked for, marked forbidden', async () => {
    provideApiClient(clientFor(session(['users.read'])))

    await router.replace('/audit')

    const now = router.currentRoute.value
    // No redirect. Sending them elsewhere would erase what they tried to reach and turn "you may
    // not" into "that is not here".
    expect(now.name).toBe('audit')
    expect(now.path).toBe('/audit')
    expect(now.meta.forbidden).toBe(true)
  })

  it('clears the mark for a visitor who does hold it', async () => {
    provideApiClient(clientFor(session(['audit.read'])))

    await router.replace('/audit')

    expect(router.currentRoute.value.name).toBe('audit')
    expect(router.currentRoute.value.meta.forbidden).toBe(false)
  })

  it('sends an anonymous visitor to sign in first, rather than telling them they may not', async () => {
    provideApiClient(clientFor(null))

    await router.replace('/audit')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query['next']).toBe('/audit')
  })
})

describe('safeNext', () => {
  it('accepts a path on this site', () => {
    expect(safeNext('/subscribers?x=1')).toBe('/subscribers?x=1')
    expect(safeNext('/')).toBe('/')
    expect(safeNext('/a/b#c')).toBe('/a/b#c')
  })

  it('refuses anything that could leave this site', () => {
    // `//evil.example` is the one that catches people out: it is protocol-relative, so a browser
    // reads it as another host while it still starts with a slash.
    expect(safeNext('//evil.example')).toBeNull()
    expect(safeNext('https://evil.example')).toBeNull()
    expect(safeNext('javascript:alert(1)')).toBeNull()
    expect(safeNext('http://localhost/whatever')).toBeNull()
    expect(safeNext('subscribers')).toBeNull()
  })

  it('refuses the ones that look like a path and are not', () => {
    // Each of these begins with a single slash and is not "//", so every hand-written rule waves
    // them through — and every one resolves to https://evil.example under the parser the browser
    // actually uses. A backslash is a path separator for special schemes, and tab, newline and
    // carriage return are stripped before parsing rather than rejected.
    for (const hostile of [
      '/\\/evil.example',
      '/\\evil.example',
      '/\t/evil.example',
      '/\n//evil.example',
      '/\r/evil.example',
    ]) {
      expect(new URL(hostile, 'https://panel.test').origin).toBe('https://evil.example')
      expect(safeNext(hostile, 'https://panel.test')).toBeNull()
    }
  })

  it('keeps the query and the fragment of a path it accepts', () => {
    expect(safeNext('/subscribers?state=GRACE#row-3', 'https://panel.test')).toBe(
      '/subscribers?state=GRACE#row-3',
    )
  })

  it('refuses anything that is not a string, which is what a repeated query key produces', () => {
    // `?next=/a&next=/b` arrives as an array, and `?next` on its own as null.
    expect(safeNext(['/a', '/b'])).toBeNull()
    expect(safeNext(null)).toBeNull()
    expect(safeNext(undefined)).toBeNull()
  })
})
