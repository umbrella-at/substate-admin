/**
 * The control that moves a world, and the two things it must do besides move it.
 */

/* It has to make everything else re-ask. Every figure here is read from the world the clock
   belongs to, so an advance that moved the clock and left the table alone would put a pre-advance
   number beside a post-advance one — the failure the analytics round was built to prevent. */

/* And it has to keep the clock itself out of that sweep: the answer to the advance IS the new
   reading, so refetching would be a request for a number already in hand. */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClockReading } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import ClockControl from '@/components/ClockControl.vue'
import { forgetWorldClock } from '@/composables/useWorldClock'
import { useAuthStore } from '@/stores/auth'

const AT_ZERO: ClockReading = { now: '2026-09-04T06:00:00Z', offsetSeconds: 0, isSandbox: true }
const A_MONTH_ON: ClockReading = {
  now: '2026-10-04T06:00:00Z',
  offsetSeconds: 30 * 24 * 60 * 60,
  isSandbox: true,
}

function stubClient(overrides: Record<string, unknown> = {}) {
  return {
    clock: vi.fn<() => Promise<ClockReading>>().mockResolvedValue(AT_ZERO),
    advanceClock: vi.fn<() => Promise<ClockReading>>().mockResolvedValue(A_MONTH_ON),
    ...overrides,
  }
}

async function open(client: ReturnType<typeof stubClient>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const pinia = createPinia()
  setActivePinia(pinia)
  // The query is guarded on the session, like every other query mounted in the frame.
  useAuthStore().adopt({
    kind: 'demo',
    permissions: ['demo.control'],
    role: { code: 'demo', name: 'Demo' },
    user: {
      createdAt: '2026-01-01T00:00:00Z',
      email: 'you@example.com',
      id: '00000000-0000-0000-0000-000000000000',
      isActive: true,
      lastLoginAt: null,
    },
    worldId: 'w',
  })

  const wrapper = mount(ClockControl, {
    global: {
      plugins: [pinia, [VueQueryPlugin, { queryClient }]],
      provide: { [apiClientKey as unknown as string]: client },
    },
  })
  await flushPromises()
  return { wrapper, queryClient }
}

function press(wrapper: Awaited<ReturnType<typeof open>>['wrapper'], label: string) {
  const found = wrapper.findAll('button').find((button) => button.text() === label)
  if (found === undefined) throw new Error(`no ${label} button`)
  return found.trigger('click')
}

beforeEach(() => {
  forgetWorldClock()
  vi.useRealTimers()
})

describe('winding the clock', () => {
  it('sends the step that was pressed', async () => {
    const client = stubClient()
    const { wrapper } = await open(client)

    await press(wrapper, 'Week')
    await flushPromises()

    expect(client.advanceClock).toHaveBeenCalledWith(7)
  })

  it('makes every other screen re-ask, and does not re-ask for the clock', async () => {
    const client = stubClient()
    const { wrapper, queryClient } = await open(client)
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await press(wrapper, 'Month')
    await flushPromises()

    const [options] = invalidate.mock.calls[0] ?? []
    const predicate = (
      options as unknown as { predicate: (query: { queryKey: unknown[] }) => boolean }
    ).predicate
    expect(predicate({ queryKey: ['subscribers', 'page'] })).toBe(true)
    expect(predicate({ queryKey: ['analytics', 'quiet'] })).toBe(true)
    expect(predicate({ queryKey: ['clock'] })).toBe(false)
    expect(queryClient.getQueryData(['clock'])).toEqual(A_MONTH_ON)
  })

  it('says how far ahead the world now is', async () => {
    const client = stubClient()
    const { wrapper } = await open(client)

    await press(wrapper, 'Month')
    await flushPromises()

    expect(wrapper.text()).toContain('30 days ahead of today')
  })

  it('refuses a custom step the API would refuse', async () => {
    const client = stubClient()
    const { wrapper } = await open(client)

    for (const typed of ['0', '-5', '400', 'soon', '']) {
      await wrapper.find('input').setValue(typed)
      expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBe('')
    }

    await wrapper.find('input').setValue('90')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('says so when the world did not move', async () => {
    const client = stubClient({ advanceClock: vi.fn().mockRejectedValue(new Error('no')) })
    const { wrapper } = await open(client)

    await press(wrapper, 'Day')
    await flushPromises()

    expect(wrapper.text()).toContain('The world did not move.')
  })
})
