/**
 * The table screen: the four states, and the two properties that make it trustworthy.
 *
 * THE ANSWER BELONGS TO THE QUESTION. Filters change faster than the network answers, and the
 * defect that produces is a page of grace subscribers under a trial filter — numbers that are
 * wrong in a way only somebody who already knew the answer would catch. It is asserted here
 * rather than left to the query library's reputation.
 *
 * AN EMPTY TABLE SAYS WHY IT IS EMPTY. Under a forgotten filter, "no rows" reads as "there is
 * nobody", which is the most convincing wrong answer this screen can give.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { ApiError, type PlanSummary, type SubscriberPage } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import type { SubscriberSummary } from '@/domain/subscribers'
import SubscribersView from '@/views/SubscribersView.vue'

const routeQuery = ref<Record<string, string | string[]>>({})
const push = vi.fn((to: { query: Record<string, string | string[]> }) => {
  routeQuery.value = to.query
  return Promise.resolve()
})
const replace = vi.fn((to: { query: Record<string, string | string[]> }) => {
  routeQuery.value = to.query
  return Promise.resolve()
})

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({ get query() {
    return routeQuery.value
  } }),
  useRouter: () => ({ push, replace }),
}))

function subscriber(over: Partial<SubscriberSummary> = {}): SubscriberSummary {
  return {
    userId: 'u-1',
    displayName: 'Ada Lovelace',
    state: 'active',
    planId: 'monthly',
    expiresAt: '2026-09-01T00:00:00Z',
    lastActiveAt: '2026-08-20T00:00:00Z',
    ...over,
  }
}

function page(over: Partial<SubscriberPage> = {}): SubscriberPage {
  return { items: [subscriber()], total: 1, page: 1, pageSize: 25, ...over }
}

const PLANS: PlanSummary[] = [
  {
    id: 'weekly',
    price: 200,
    currency: 'USD',
    periodUnit: 'days',
    periodCount: 7,
    trialDays: 0,
    graceDays: 2,
  },
]

function render(subscribers: (params: URLSearchParams, signal: AbortSignal) => Promise<unknown>) {
  const client = {
    subscribers,
    plans: () => Promise.resolve(PLANS),
  }
  return mount(SubscribersView, {
    global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
      provide: { [apiClientKey as symbol]: client },
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

beforeEach(() => {
  routeQuery.value = {}
  push.mockClear()
  replace.mockClear()
  vi.useRealTimers()
})

describe('the four states', () => {
  it('shows a placeholder shaped like the table before the first answer', () => {
    const view = render(() => new Promise(() => {}))
    expect(view.find('[aria-busy="true"]').exists()).toBe(true)
    expect(view.text()).toContain('Loading subscribers')
  })

  it('offers a retry when the request fails, instead of sending anyone to reload', async () => {
    const view = render(() => Promise.reject(new ApiError(500, null)))
    await flushPromises()
    expect(view.text()).toContain('The service could not be reached.')
    expect(view.text()).toContain('Try again')
  })

  it('shows the rows when they arrive', async () => {
    const view = render(() => Promise.resolve(page()))
    await flushPromises()
    expect(view.text()).toContain('Ada Lovelace')
    expect(view.text()).toContain('1 subscriber')
  })

  it('says an empty world is empty', async () => {
    const view = render(() => Promise.resolve(page({ items: [], total: 0 })))
    await flushPromises()
    expect(view.text()).toContain('This world has no subscribers yet')
  })

  it('blames the filters when they are what emptied the table, and offers to clear them', async () => {
    routeQuery.value = { state: ['grace'] }
    const view = render(() => Promise.resolve(page({ items: [], total: 0 })))
    await flushPromises()
    expect(view.text()).toContain('No subscribers match these filters')
    expect(view.text()).toContain('Clear filters')
  })
})

/**
 * EXACTLY ONE OF THEM, WHICH IS A DIFFERENT CLAIM FROM "THE RIGHT ONE IS THERE".
 *
 * The four states are a choice, and every test above asks only whether the branch it cares about
 * rendered. None of them can fail on a second branch rendering beside it — `toContain` is a lower
 * bound, and a lower bound cannot see a neighbour.
 *
 * That is not hypothetical here. A `v-if` placed between a `v-else-if` and its `v-else` silently
 * starts a new chain and orphans the `v-else`, which then renders unconditionally; the result is
 * valid Vue, so neither the compiler, nor vue-tsc, nor eslint says anything. Introduced into this
 * view it puts the table on screen underneath the loading skeleton and underneath the error, and
 * every one of the tests above still passed. It is the same slip that drew every column header
 * twice one file over.
 *
 * So this asks the other half of the question: in each state, which regions are on screen.
 */
describe('the four states are a choice', () => {
  function showing(view: ReturnType<typeof render>) {
    return {
      loading: view.text().includes('Loading subscribers'),
      failed: view.text().includes('Try again'),
      table: view.find('table').exists(),
    }
  }

  it('shows only the placeholder while the first answer is outstanding', async () => {
    const view = render(() => new Promise(() => {}))
    await flushPromises()
    expect(showing(view)).toEqual({ loading: true, failed: false, table: false })
  })

  it('shows only the failure when the request fails', async () => {
    const view = render(() => Promise.reject(new ApiError(500, null)))
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: true, table: false })
  })

  it('shows only the table once there is one', async () => {
    const view = render(() => Promise.resolve(page()))
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: false, table: true })
  })

  // Empty is not a fourth region: it is the table with nothing in it, plus a sentence. The table
  // must still be there, or the header row would vanish along with the rows.
  it('keeps the table when it is empty, and says why', async () => {
    const view = render(() => Promise.resolve(page({ items: [], total: 0 })))
    await flushPromises()
    expect(showing(view)).toEqual({ loading: false, failed: false, table: true })
    expect(view.text()).toContain('This world has no subscribers yet')
  })
})

describe('the question and the answer', () => {
  it('asks the API for what the address says', async () => {
    const asked: string[] = []
    routeQuery.value = { state: ['grace'], sort: '-expiresAt', page: '2' }
    render((params) => {
      asked.push(params.toString())
      return Promise.resolve(page())
    })
    await flushPromises()
    expect(asked[0]).toContain('state=grace')
    expect(asked[0]).toContain('sort=-expiresAt')
    expect(asked[0]).toContain('page=2')
  })

  // The defect this prevents: two requests in flight, the slow one answering the older question,
  // and its rows landing on screen under the newer filter.
  it('never shows the answer to a question that has been replaced', async () => {
    const pending: { resolve: (value: SubscriberPage) => void; params: string }[] = []
    const view = render(
      (params) =>
        new Promise<SubscriberPage>((resolve) => {
          pending.push({ resolve, params: params.toString() })
        }),
    )
    await flushPromises()

    routeQuery.value = { state: ['trial'] }
    await flushPromises()

    // The stale answer for the unfiltered question comes back last, and loudly.
    const stale = pending.find((entry) => !entry.params.includes('state='))
    stale?.resolve(page({ items: [subscriber({ displayName: 'Stale Person' })] }))
    await flushPromises()

    expect(view.text()).not.toContain('Stale Person')
  })

  it('cancels the request it stopped waiting for', async () => {
    const signals: AbortSignal[] = []
    render((_params, signal) => {
      signals.push(signal)
      return new Promise(() => {})
    })
    await flushPromises()

    routeQuery.value = { state: ['trial'] }
    await flushPromises()

    expect(signals[0]?.aborted).toBe(true)
  })
})

describe('the address bar', () => {
  it('goes back to the first page when a filter changes', async () => {
    routeQuery.value = { page: '4' }
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    await view.findAll('input[type="checkbox"]')[0]?.trigger('change')
    expect(push).toHaveBeenCalled()
    expect(push.mock.calls[0]?.[0]?.query).not.toHaveProperty('page')
  })

  // Typing produces one question per keystroke. Forwarding those as history entries would mean
  // leaving a search took as many presses of the back button as the name had letters.
  it('makes starting a search a step the back button can undo', async () => {
    vi.useFakeTimers()
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    const search = view.get('input[type="text"], input:not([type])')
    await search.setValue('ada')
    vi.advanceTimersByTime(400)
    await flushPromises()

    expect(push).toHaveBeenCalledTimes(1)
    expect(push.mock.calls[0]?.[0]?.query).toMatchObject({ q: 'ada' })
  })

  // Refining is not a place anybody navigates back to, and one entry per letter would mean
  // leaving a search took as many presses of back as the name had letters.
  it('does not add an entry for every letter after that', async () => {
    vi.useFakeTimers()
    routeQuery.value = { q: 'ada' }
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    const search = view.get('input[type="text"], input:not([type])')
    await search.setValue('adam')
    vi.advanceTimersByTime(400)
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(replace).toHaveBeenCalledTimes(1)
    expect(replace.mock.calls[0]?.[0]?.query).toMatchObject({ q: 'adam' })
  })

  it('waits for the typing to stop before asking', async () => {
    vi.useFakeTimers()
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    const search = view.get('input[type="text"], input:not([type])')
    await search.setValue('a')
    await search.setValue('ad')
    await search.setValue('ada')
    vi.advanceTimersByTime(400)
    await flushPromises()

    expect(push).toHaveBeenCalledTimes(1)
  })

  // The back button, a pasted link and the clear-filters button all arrive the same way, and a
  // field still showing a search nobody is applying is a lie about what the table is showing.
  it('lets go of text the address no longer carries', async () => {
    routeQuery.value = { q: 'ada' }
    const view = render(() => Promise.resolve(page()))
    await flushPromises()
    expect(
      (view.get('input[type="text"], input:not([type])').element as HTMLInputElement).value,
    ).toBe('ada')

    routeQuery.value = {}
    await flushPromises()
    expect(
      (view.get('input[type="text"], input:not([type])').element as HTMLInputElement).value,
    ).toBe('')
  })

  // A plan is a category, so more than one of them is a sensible question. The backend takes the
  // repeated parameter the same way it takes states.
  it('carries more than one plan in the address', async () => {
    const asked: string[] = []
    routeQuery.value = { planId: ['weekly', 'annual'] }
    render((params) => {
      asked.push(params.toString())
      return Promise.resolve(page())
    })
    await flushPromises()
    expect(asked[0]).toContain('planId=weekly')
    expect(asked[0]).toContain('planId=annual')
  })

  // The order over states is a name, not a direction, so it is turned on by a control that says
  // what it does rather than by an arrow on a column that has no magnitude.
  it('turns the urgency order on by name', async () => {
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    const control = view
      .findAll('label')
      .find((label) => label.text().includes('Most urgent first'))
    expect(control).toBeDefined()

    await control?.find('input[type="checkbox"]').trigger('change')
    expect(push).toHaveBeenCalled()
    expect(push.mock.calls[0]?.[0]?.query).toMatchObject({ sort: 'state' })
  })

  it('turns it off again, back to the default order', async () => {
    routeQuery.value = { sort: 'state' }
    const view = render(() => Promise.resolve(page()))
    await flushPromises()

    const control = view
      .findAll('label')
      .find((label) => label.text().includes('Most urgent first'))
    await control?.find('input[type="checkbox"]').trigger('change')
    // The default order stays out of the address, so turning it off leaves nothing behind.
    expect(push.mock.calls[0]?.[0]?.query).not.toHaveProperty('sort')
  })

  it('sorts by a link, so the order can be opened in a new tab', async () => {
    const view = render(() => Promise.resolve(page()))
    await flushPromises()
    const header = view.findAllComponents(RouterLinkStub)[0]
    expect(header?.props('to')).toEqual({ query: { sort: 'displayName' } })
  })

  it('reverses a column that is already sorted, rather than clearing it', async () => {
    routeQuery.value = { sort: 'displayName' }
    const view = render(() => Promise.resolve(page()))
    await flushPromises()
    expect(view.findAllComponents(RouterLinkStub)[0]?.props('to')).toEqual({
      query: { sort: '-displayName' },
    })
  })
})
