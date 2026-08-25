/**
 * The four request states, asserted on the first screen that has them.
 *
 * The point of writing these tests now rather than in the round where a table makes them obvious:
 * loading, empty, error and data are cheap to claim and easy to leave half-built, and the way that
 * gets discovered is a blank panel in front of somebody. Each one is checked here for the thing
 * that makes it useful — the skeleton has the SHAPE of the answer, the empty state says what to do
 * about it, the error state offers the retry — not merely for existing.
 *
 * The sign-out test is the security one: TanStack Query's cache is keyed by query and not by
 * person, so a sign-out that leaves it populated shows the next person to use the browser the
 * previous one's data while their own request is still in flight.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type MeResponse } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import { useAuthStore } from '@/stores/auth'
import DashboardView from '@/views/DashboardView.vue'

const replace = vi.fn()

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRouter: () => ({ replace }),
}))

function me(permissions: string[]): MeResponse {
  return {
    kind: 'user',
    permissions,
    role: { code: 'support', name: 'Support' },
    user: {
      createdAt: '2026-01-01T00:00:00Z',
      email: 'operator@example.com',
      id: '00000000-0000-0000-0000-000000000000',
      isActive: true,
      lastLoginAt: '2026-08-25T09:00:00Z',
    },
  }
}

function mountDashboard(meResult: () => Promise<MeResponse>) {
  const client = {
    me: vi.fn(meResult),
    logout: vi.fn<() => Promise<null>>().mockResolvedValue(null),
    setAccessToken: vi.fn(),
  }
  // Retries off: this is about what each state looks like, and a real retry policy would only
  // make the error test take three times as long to reach the same assertion.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  const wrapper = mount(DashboardView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      provide: { [apiClientKey as unknown as string]: client },
    },
  })
  return { wrapper, client, queryClient }
}

beforeEach(() => {
  setActivePinia(createPinia())
  // The router guard is what normally puts a session here. Without one the query is correctly
  // disabled and the panel would wait forever, which is the behaviour sign-out relies on.
  useAuthStore().adopt(me(['users.read']))
  replace.mockReset()
})

describe('loading', () => {
  it('shows the shape of the answer rather than a spinner', async () => {
    const { wrapper } = mountDashboard(() => new Promise<MeResponse>(() => {}))
    await flushPromises()

    const blocks = wrapper.findAll('.skeleton')
    // Three labelled fields and a row of chips: what is about to arrive, in the places it will
    // arrive in, so nothing on the panel moves when it does.
    expect(blocks.length).toBeGreaterThanOrEqual(8)
    expect(wrapper.find('[role="status"]').text()).toContain('Loading')
    expect(wrapper.text()).not.toContain('Signed in as')
  })
})

describe('data', () => {
  it('shows the address, the role and every permission as its own chip', async () => {
    const { wrapper } = mountDashboard(async () => me(['users.read', 'plans.read']))
    await flushPromises()

    expect(wrapper.text()).toContain('operator@example.com')
    expect(wrapper.text()).toContain('Support')
    expect(wrapper.text()).toContain('support')

    const chips = wrapper.findAll('.font-numeric.bg-surface-2')
    expect(chips.map((chip) => chip.text())).toEqual(['users.read', 'plans.read'])
    // The round shape belongs to the five subscription states. A permission is a fact, not a state.
    for (const chip of chips) expect(chip.classes()).toContain('rounded-control')
  })

  it('refreshes the session store from the answer', async () => {
    const { wrapper } = mountDashboard(async () => me(['audit.read']))
    await flushPromises()

    expect(wrapper.text()).toContain('audit.read')
    expect([...useAuthStore().permissions]).toEqual(['audit.read'])
  })
})

describe('empty', () => {
  it('says what can be done about a role that grants nothing yet', async () => {
    const { wrapper } = mountDashboard(async () => me([]))
    await flushPromises()

    expect(wrapper.findAll('.font-numeric.bg-surface-2')).toHaveLength(0)
    const text = wrapper.text()
    expect(text).toContain('An administrator can add permissions')
    expect(text).not.toContain('No data')
  })
})

describe('error', () => {
  it('says what happened, offers the retry, and does not apologise', async () => {
    const { wrapper, client } = mountDashboard(() => Promise.reject(new TypeError('Failed to fetch')))
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('could not be reached')
    expect(text).not.toContain('Something went wrong')
    expect(text).not.toContain('Sorry')

    const retry = wrapper.findAll('button').find((button) => button.text() === 'Try again')
    expect(retry).toBeDefined()
    expect(client.me).toHaveBeenCalledTimes(1)
    await retry?.trigger('click')
    await flushPromises()
    expect(client.me).toHaveBeenCalledTimes(2)
  })

  it('reports a rate limit in the words the API used, rather than as an outage', async () => {
    const limited = new ApiError(429, {
      code: 'RATE_LIMITED',
      message: 'Too many attempts. Try again in a few minutes.',
    } as never)
    const { wrapper } = mountDashboard(() => Promise.reject(limited))
    await flushPromises()

    expect(wrapper.text()).toContain('Too many attempts')
  })
})

describe('sign out', () => {
  it('is not the loudest control on a screen that has no primary action', async () => {
    const { wrapper } = mountDashboard(async () => me(['users.read']))
    await flushPromises()

    const buttons = wrapper.findAll('button')
    for (const button of buttons) expect(button.classes()).not.toContain('bg-accent-fill')
    expect(buttons.some((button) => button.text() === 'Sign out')).toBe(true)
  })

  it('empties the query cache, so the next person cannot be shown this one', async () => {
    const { wrapper, client, queryClient } = mountDashboard(async () => me(['users.read']))
    await flushPromises()
    expect(queryClient.getQueryData(['auth', 'me'])).toBeDefined()

    const signOut = wrapper.findAll('button').find((button) => button.text() === 'Sign out')
    await signOut?.trigger('click')
    await flushPromises()

    expect(client.logout).toHaveBeenCalled()
    expect(client.setAccessToken).toHaveBeenCalledWith(null)
    expect(queryClient.getQueryData(['auth', 'me'])).toBeUndefined()
    expect(useAuthStore().isAuthenticated).toBe(false)
    expect(replace).toHaveBeenCalledWith({ name: 'login' })
  })

  it('still ends the session locally when the server cannot be told', async () => {
    const { wrapper, client, queryClient } = mountDashboard(async () => me(['users.read']))
    await flushPromises()
    client.logout.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    const signOut = wrapper.findAll('button').find((button) => button.text() === 'Sign out')
    await signOut?.trigger('click')
    await flushPromises()

    // Refusing to sign out because the network is down would leave someone signed in on a machine
    // they are walking away from.
    expect(useAuthStore().isAuthenticated).toBe(false)
    expect(queryClient.getQueryData(['auth', 'me'])).toBeUndefined()
    expect(replace).toHaveBeenCalledWith({ name: 'login' })
  })
})
