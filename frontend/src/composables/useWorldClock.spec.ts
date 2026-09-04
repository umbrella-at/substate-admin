/**
 * The defect this composable exists to prevent, asserted from both sides.
 */

/* A world wound a month forward holds activity up to a month in the browser's future.
   `formatSince` computes `now - at`, gets a negative number, and answers "just now" for the whole
   column — while the backend reports a third of those rows as quiet. No error, no dash. */

/* The second test is the one that would be missing if this were only a bug fix: it holds the
   browser's clock still and moves the world's, which is the only way to tell "reads the world's
   clock" from "happens to work today". */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import type { ClockReading } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import { forgetWorldClock, useWorldClock, useWorldNow } from '@/composables/useWorldClock'
import { formatSince } from '@/domain/elapsed'
import { useAuthStore } from '@/stores/auth'

const DAY = 24 * 60 * 60 * 1000
const REAL_NOW = Date.parse('2026-09-04T12:00:00Z')

/** Three days after the browser's now, and twenty-seven days before a world wound a month. */
const SEEN_AT = new Date(REAL_NOW + 3 * DAY)

const Reader = defineComponent({
  setup() {
    const now = useWorldNow()
    return () => h('span', formatSince(SEEN_AT, now.value))
  },
})

const Framed = defineComponent({
  setup() {
    useWorldClock()
    return () => h(Reader)
  },
})

function session() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().adopt({
    kind: 'demo',
    permissions: [],
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
  return pinia
}

beforeEach(() => {
  forgetWorldClock()
  vi.useFakeTimers()
  vi.setSystemTime(REAL_NOW)
})

describe('activity against a world that has been wound', () => {
  it('reads as "just now" when the browser clock is used instead', () => {
    // Not a hypothetical: this is what the column did before the offset reached it. The date is
    // in the future, `formatSince` floors at "just now", and nothing anywhere reports a problem.
    expect(formatSince(SEEN_AT, Date.now())).toBe('just now')
  })

  it('reads as the world sees it once the offset arrives', async () => {
    const pinia = session()
    const client = {
      clock: vi.fn<() => Promise<ClockReading>>().mockResolvedValue({
        now: new Date(REAL_NOW + 30 * DAY).toISOString(),
        offsetSeconds: 30 * 24 * 60 * 60,
        isSandbox: true,
        daysLeft: 335,
      }),
    }
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const wrapper = mount(Framed, {
      global: {
        plugins: [pinia, [VueQueryPlugin, { queryClient }]],
        provide: { [apiClientKey as unknown as string]: client },
      },
    })
    await flushPromises()

    // The browser's clock has not moved. The world's has, and the column follows it.
    expect(wrapper.text()).toBe('27 days ago')
  })

  it('forgets the offset when a session ends', async () => {
    forgetWorldClock()
    const wrapper = mount(Reader)

    // Back to the browser's own clock, which is the right answer for a world nobody has wound —
    // and the wrong one to keep from the world somebody just left.
    expect(wrapper.text()).toBe('just now')
  })
})
