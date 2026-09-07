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

import { ApiError, type ClockReading } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import ClockControl from '@/components/ClockControl.vue'
import { forgetWorldClock } from '@/composables/useWorldClock'
import { useAuthStore } from '@/stores/auth'

const AT_ZERO: ClockReading = {
  now: '2026-09-04T06:00:00Z',
  offsetSeconds: 0,
  isSandbox: true,
  daysLeft: 365,
}
const A_MONTH_ON: ClockReading = {
  now: '2026-10-04T06:00:00Z',
  offsetSeconds: 30 * 24 * 60 * 60,
  isSandbox: true,
  daysLeft: 335,
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

  it('does not offer a step the world has no room for', async () => {
    // The refusal carries the number of days left, but only after a press. A control that offers
    // what will be refused is a control that has to be pressed to be understood.
    const client = stubClient({
      clock: vi.fn().mockResolvedValue({ ...AT_ZERO, offsetSeconds: 360 * 86400, daysLeft: 5 }),
    })
    const { wrapper } = await open(client)

    const month = wrapper.findAll('button').find((button) => button.text() === 'Month')
    const day = wrapper.findAll('button').find((button) => button.text() === 'Day')
    expect(month?.attributes('disabled')).toBe('')
    expect(day?.attributes('disabled')).toBeUndefined()

    await wrapper.find('input').setValue('30')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBe('')
  })

  it('says so when the world did not move', async () => {
    const client = stubClient({ advanceClock: vi.fn().mockRejectedValue(new Error('no')) })
    const { wrapper } = await open(client)

    await press(wrapper, 'Day')
    await flushPromises()

    expect(wrapper.text()).toContain('The world did not move.')
  })

  it('passes on what the service said when the world has been wound as far as it goes', async () => {
    // The sentence carries the number of days left, and that number is the only thing that lets
    // somebody choose a smaller step. A fixed "it did not move" throws it away.
    const client = stubClient({
      advanceClock: vi.fn().mockRejectedValue(
        new ApiError(422, {
          code: 'VALIDATION_ERROR',
          message: 'This world has been wound as far as it goes. 65 of its 365 days are left.',
          field: 'days',
        } as never),
      ),
    })
    const { wrapper } = await open(client)

    await press(wrapper, 'Month')
    await flushPromises()

    expect(wrapper.text()).toContain('65 of its 365 days are left')
  })
})

/** The one number on this panel that IS the subject, and it had no loading state: while the read
 *  was in flight the panel drew the browser's own date under the label "The demonstration world",
 *  which is a confident answer to the question the control exists to ask. */
describe('before the reading arrives', () => {
  it("shows the shape of the reading rather than the browser's own clock", async () => {
    const { wrapper } = await open(stubClient({ clock: () => new Promise(() => {}) }))

    expect(wrapper.find('.skeleton').exists()).toBe(true)
    // Neither label, and no date: the fallback says `isSandbox` is false, so the panel called a
    // sandbox the base world and dated it from the browser.
    expect(wrapper.text()).not.toContain('Your world')
    expect(wrapper.text()).not.toContain('The demonstration world')
    expect(wrapper.text()).toContain("Reading this world's clock")
  })

  it('shows the world once it has answered', async () => {
    const { wrapper } = await open(stubClient())

    expect(wrapper.find('.skeleton').exists()).toBe(false)
    expect(wrapper.text()).toContain('Your world')
  })
})

/** The signature element, and the two things that make it one. */
describe('what the control looks like', () => {
  it('marks the month jump, which is the step the design file names', async () => {
    const { wrapper } = await open(stubClient())

    const month = wrapper.findAll('button').find((each) => each.text() === 'Month')
    expect(month!.classes()).toContain('border-accent-text')
    // Marked by its outline rather than by a fill: this control is in the frame, so a filled
    // element here would be a second one on every screen that has its own.
    expect(month!.classes()).not.toContain('bg-accent-fill')
  })

  it('shows a wound world differently from one at today', async () => {
    const atToday = await open(stubClient())
    expect(atToday.wrapper.find('section').classes()).not.toContain('border-l-accent-text')
    expect(atToday.wrapper.text()).not.toContain('ahead of today')

    forgetWorldClock()
    const wound = await open(stubClient({ clock: vi.fn().mockResolvedValue(A_MONTH_ON) }))
    expect(wound.wrapper.find('section').classes()).toContain('border-l-accent-text')
    expect(wound.wrapper.text()).toContain('30 days ahead of today')
  })

  // A button that carries `busy` and keeps its name announces the wait to a screen reader and to
  // nobody else — and one flag for four buttons announced it on all of them.
  it('renames the step that is out, and only that one', async () => {
    let release = (_: unknown) => {}
    const client = stubClient({
      advanceClock: vi.fn(() => new Promise((resolve) => (release = resolve))),
    })
    const { wrapper } = await open(client)

    await press(wrapper, 'Month')
    await flushPromises()

    expect(wrapper.text()).toContain('A month on…')
    expect(wrapper.text()).not.toContain('A week on…')
    expect(wrapper.text()).not.toContain('A day on…')
    release(A_MONTH_ON)
  })
})
