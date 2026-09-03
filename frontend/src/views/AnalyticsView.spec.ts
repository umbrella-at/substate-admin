/**
 * Five figures, and four states each that are a choice rather than a stack. A figure has its own
 * request so it can fail alone, and a screen whose figures shared one looks identical until the
 * day an endpoint is slow.
 */

/* A `v-if` slipped between a `v-else-if` and its `v-else` compiles, type-checks and lints, and
   puts the plot under the skeleton. So each state is asserted for absence as well as presence. */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import {
  ApiError,
  type FlowResponse,
  type FunnelResponse,
  type QuietResponse,
  type RevenueResponse,
  type StatesResponse,
} from '@/api/client'
import { apiClientKey } from '@/api/provide'
import AnalyticsView from '@/views/AnalyticsView.vue'

const routeQuery = ref<Record<string, string | string[]>>({})
const push = vi.fn((to: { query: Record<string, string | string[]> }) => {
  routeQuery.value = to.query
  return Promise.resolve()
})

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({
    get query() {
      return routeQuery.value
    },
  }),
  useRouter: () => ({ push }),
}))

const FUNNEL: FunnelResponse = {
  since: '2026-06-05T00:00:00Z',
  until: '2026-09-03T00:00:00Z',
  stages: [
    { stage: 'arrived', count: 168 },
    { stage: 'paid', count: 122 },
    { stage: 'renewed', count: 43 },
  ],
  startedATrial: 129,
}

const FLOW: FlowResponse = {
  since: '2026-06-05T00:00:00Z',
  until: '2026-09-03T00:00:00Z',
  granularity: 'week',
  points: [
    { startsAt: '2026-08-24T00:00:00Z', joined: 15, left: 27 },
    { startsAt: '2026-08-31T00:00:00Z', joined: 7, left: 9 },
  ],
}

const STATES: StatesResponse = {
  states: [
    { state: 'grace', count: 3 },
    { state: 'trial', count: 22 },
    { state: 'active', count: 239 },
    { state: 'cancelled', count: 41 },
    { state: 'expired', count: 46 },
  ],
  total: 351,
}

const QUIET: QuietResponse = {
  bands: [
    { fromDays: 30, toDays: 60, count: 22 },
    { fromDays: 60, toDays: 90, count: 12 },
    { fromDays: 90, toDays: null, count: 8 },
  ],
  total: 42,
}

const REVENUE: RevenueResponse = {
  currency: 'USD',
  months: [
    { startsAt: '2026-08-01T00:00:00Z', amount: 164700 },
    { startsAt: '2026-09-01T00:00:00Z', amount: 45250 },
  ],
}

function health(seeded: boolean) {
  return {
    status: 'ok',
    version: '0.0.0',
    commit: 'test',
    db: true,
    world: { id: 'base', seeded, subscribers: seeded ? 351 : 0, events: seeded ? 3832 : 0 },
  }
}

type Answers = {
  funnel?: () => Promise<unknown>
  flow?: () => Promise<unknown>
  states?: () => Promise<unknown>
  quiet?: () => Promise<unknown>
  revenue?: () => Promise<unknown>
  seeded?: boolean
}

function render(over: Answers = {}) {
  const client = {
    funnel: over.funnel ?? (() => Promise.resolve(FUNNEL)),
    flow: over.flow ?? (() => Promise.resolve(FLOW)),
    states: over.states ?? (() => Promise.resolve(STATES)),
    quiet: over.quiet ?? (() => Promise.resolve(QUIET)),
    revenue: over.revenue ?? (() => Promise.resolve(REVENUE)),
    health: () => Promise.resolve(health(over.seeded ?? true)),
  }
  // The figures are stubbed: they draw to a canvas, which is a picture rather than a fact, and
  // what this file is about is which region of the screen is on it.
  return mount(AnalyticsView, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: { [apiClientKey as symbol]: client },
      stubs: { BarFigure: true, LineFigure: true },
    },
  })
}

beforeEach(() => {
  routeQuery.value = {}
  push.mockClear()
})

describe('the five figures', () => {
  it('asks each of its questions and says where each answer came from', async () => {
    const view = render()
    await flushPromises()

    for (const question of [
      'Are we growing or shrinking?',
      'Where do we lose them?',
      'What is in the base right now?',
      'Who pays but has stopped turning up?',
      'How much money is coming in?',
    ]) {
      expect(view.text()).toContain(question)
    }
    expect(view.text()).toContain('Standing now, from the engine')
    expect(view.text()).toContain('Movements in the period, from the event journal')
  })

  it('answers each question with a number rather than with its plot', async () => {
    const view = render()
    await flushPromises()

    expect(view.text()).toContain('79 of the 122 who paid did not renew')
    expect(view.text()).toContain('351 subscriptions')
    expect(view.text()).toContain('42 subscribers')
    expect(view.text()).toContain('2099.50 USD')
    expect(view.text()).toContain('22 arrivals against 36 departures')
  })

  it('says how many arrived on a trial without making it a stage', async () => {
    const view = render()
    await flushPromises()

    expect(view.text()).toContain('129 of them arrived on a plan with a trial')
    // Three bars, and the trial is not one of them.
    expect(view.text()).not.toContain('Started a trial')
  })
})

/**
 * Each figure fails alone. The assertion that matters is that the other four still answer: a
 * screen blanking on one failure would pass "shows the failure" and fail its reader.
 */
describe('a figure that fails', () => {
  it('says so where it is and leaves the rest standing', async () => {
    const view = render({ revenue: () => Promise.reject(new ApiError(500, null)) })
    await flushPromises()

    expect(view.text()).toContain('The service could not be reached.')
    expect(view.text()).toContain('Try again')
    expect(view.text()).toContain('351 subscriptions')
    expect(view.text()).toContain('79 of the 122 who paid did not renew')
  })

  it('offers a retry rather than telling anybody to reload', async () => {
    const view = render({ states: () => Promise.reject(new ApiError(500, null)) })
    await flushPromises()
    expect(view.text()).toContain('Try again')
    expect(view.text()).not.toContain('351 subscriptions')
  })
})

describe('the four states of one figure', () => {
  const QUESTION = 'What is in the base right now?'

  /** The one figure's own panel, not the screen it is on: the screen contains all five. */
  function panel(view: ReturnType<typeof render>) {
    return view.findAll('section.rounded-panel').find((each) => each.text().includes(QUESTION))!
  }

  // `plot` is read off the DOM rather than off the answer's text, which is what catches a broken
  // `v-if` chain: an orphaned `v-else` renders the plot UNDER the skeleton, and a check that only
  // looked for the number would see an empty plot and call it absent.
  function showing(view: ReturnType<typeof render>) {
    const frame = panel(view)
    const text = frame.text()
    return {
      loading: frame.find('.skeleton').exists(),
      failed: text.includes('Try again'),
      empty: text.includes('There are no subscriptions in this world yet.'),
      plot: frame.find('bar-figure-stub').exists(),
    }
  }

  it('shows only the placeholder before the first answer', async () => {
    const view = render({ states: () => new Promise(() => {}) })
    await flushPromises()
    expect(showing(view)).toEqual({ loading: true, failed: false, empty: false, plot: false })
  })

  it('shows only the failure when the request fails', async () => {
    const view = render({ states: () => Promise.reject(new ApiError(500, null)) })
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: true, empty: false, plot: false })
  })

  // An empty world is not an error and not a blank panel: it is a sentence saying what would put
  // something here. There is no plot, because a plot of nothing is a rectangle.
  it('shows only the invitation when the world holds nothing', async () => {
    const view = render({ states: () => Promise.resolve({ states: [], total: 0 }) })
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: false, empty: true, plot: false })
  })

  it('shows only the answer once there is one', async () => {
    const view = render()
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: false, empty: false, plot: true })
    expect(panel(view).text()).toContain('351 subscriptions')
  })
})

/**
 * A world that was not built says so once, for the screen. Five copies of the refusal would be
 * one sentence five times, each blaming its own endpoint.
 */
describe('a world that was not built', () => {
  it('replaces the figures rather than appearing inside each of them', async () => {
    const view = render({ seeded: false })
    await flushPromises()

    expect(view.text()).toContain('The demonstration world was not built.')
    expect(view.text()).not.toContain('What is in the base right now?')
  })

  it('leaves the period control alone, because it is the screen and not a figure', async () => {
    const view = render({ seeded: false })
    await flushPromises()
    expect(view.text()).toContain('Last 90 days')
  })
})

describe('the period', () => {
  it('marks the one in force and writes a change into the address', async () => {
    const view = render()
    await flushPromises()

    const pressed = view.findAll('button').filter((b) => b.attributes('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(pressed[0]!.text()).toBe('Last 90 days')

    await view
      .findAll('button')
      .find((b) => b.text() === 'Last 30 days')!
      .trigger('click')
    expect(push).toHaveBeenCalledWith({ query: { period: '30d' } })
  })

  // No filled control on this screen: the figures spend the accent, and docs/design.md allows one
  // filled element per screen for the action that matters. This screen has no action.
  it('has no filled control', async () => {
    const view = render()
    await flushPromises()
    expect(view.html()).not.toContain('bg-accent-fill')
  })
})
