/**
 * The card screen: four states for the card, four for the feed, and a fifth answer that is not an
 * error.
 *
 * TWO REQUESTS, RENDERED INDEPENDENTLY. The card comes from the engine and the feed from Postgres,
 * so one can be there while the other is not. A card over a failed feed still does its job; a
 * single gate over both would take the working half down with the broken one.
 *
 * A 404 IS NOT AN ERROR. "There is no such subscriber" and "the request failed" are different
 * answers and only one of them is worth a retry button — and the base world is rebuilt at every
 * restart, so a link from yesterday naming somebody who is gone is the ordinary way to arrive here.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type SubscriberDetail, type SubscriberEventPage } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import SubscriberView from '@/views/SubscriberView.vue'

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({ params: { userId: 'sub-0001' } }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

function detail(): SubscriberDetail {
  return {
    subscriber: {
      userId: 'sub-0001',
      displayName: 'Ada Lovelace',
      state: 'active',
      planId: 'monthly',
      accessUntil: '2026-10-16T00:00:00Z',
      expiresAt: '2026-10-16T00:00:00Z',
      trialEndsAt: null,
      graceEndsAt: null,
      cancelledAt: null,
      pendingPlanId: null,
      lastActiveAt: null,
      promoCode: null,
      referrerId: null,
    },
    plan: {
      id: 'monthly',
      price: 500,
      currency: 'USD',
      periodUnit: 'months',
      periodCount: 1,
      trialDays: 14,
      graceDays: 5,
    },
    promoCode: null,
    referrerId: null,
    referrerProgramId: null,
    referralProgramId: null,
    trialStartedAt: null,
  }
}

function feed(items: SubscriberEventPage['items'] = []): SubscriberEventPage {
  return { items, total: items.length, page: 1, pageSize: 25 }
}

const EVENT = {
  id: 'e-1',
  type: 'subscription.cancelled',
  occurredAt: '2026-09-02T05:09:00Z',
  payload: { accessUntil: '2026-10-16T00:00:00Z' },
}

async function render(over: { card?: unknown; events?: unknown } = {}) {
  const wrapper = mount(SubscriberView, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: {
        [apiClientKey as symbol]: {
          subscriber: vi.fn(() =>
            over.card instanceof Error
              ? Promise.reject(over.card)
              : Promise.resolve(over.card ?? detail()),
          ),
          subscriberEvents: vi.fn(() =>
            over.events instanceof Error
              ? Promise.reject(over.events)
              : Promise.resolve(over.events ?? feed()),
          ),
          plans: vi.fn(async () => []),
          referralPrograms: vi.fn(async () => []),
          operate: vi.fn(),
        },
      },
      stubs: {
        RouterLink: RouterLinkStub,
        SubscriberOperations: { template: '<div data-test="operations" />' },
        // The chip explains itself through a tooltip, which needs a provider this screen is not
        // about. Its own spec covers what it says.
        StateChip: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('the four states of the card', () => {
  // The shape of what is coming, not a spinner: a header bar and the rows it will have, so the
  // page does not resize when they arrive.
  it('shows the shape of the card while it is loading', async () => {
    const wrapper = mount(SubscriberView, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
        provide: {
          [apiClientKey as symbol]: {
            subscriber: vi.fn(() => new Promise(() => {})),
            subscriberEvents: vi.fn(() => new Promise(() => {})),
            plans: vi.fn(async () => []),
            referralPrograms: vi.fn(async () => []),
            operate: vi.fn(),
          },
        },
        stubs: { RouterLink: RouterLinkStub, StateChip: { template: '<span />' } },
      },
    })

    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Loading subscriber')
    // And none of the other three.
    expect(wrapper.text()).not.toContain('Try again')
    expect(wrapper.text()).not.toContain('There is no subscriber')
    expect(wrapper.find('h1').exists()).toBe(false)
  })

  it('shows the card when it arrives', async () => {
    const wrapper = await render()

    expect(wrapper.find('h1').text()).toBe('Ada Lovelace')
    expect(wrapper.find('[data-test="operations"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Try again')
  })

  // The way out is the table rather than another attempt at an id that does not exist.
  it('says there is no such subscriber, and offers no retry', async () => {
    const wrapper = await render({
      card: new ApiError(404, { code: 'NOT_FOUND', message: 'Nope.', field: null }),
    })

    expect(wrapper.text()).toContain('There is no subscriber')
    expect(wrapper.text()).toContain('Back to subscribers')
    expect(wrapper.text()).not.toContain('Try again')
  })

  it('says what failed and offers the retry', async () => {
    const wrapper = await render({
      card: new ApiError(403, {
        code: 'PERMISSION_DENIED',
        message: 'You do not have permission to do that.',
        field: null,
      }),
    })

    expect(wrapper.text()).toContain('You do not have permission to do that.')
    expect(wrapper.text()).toContain('Try again')
    expect(wrapper.text()).not.toContain('There is no subscriber')
  })

  // A failure that is not the API's opinion. The panel must not put a network error's message on
  // screen as though the service had said it.
  it('does not repeat a transport failure as though the service had spoken', async () => {
    const wrapper = await render({ card: new TypeError('Failed to fetch') })

    expect(wrapper.text()).toContain('The service could not be reached.')
    expect(wrapper.text()).not.toContain('Failed to fetch')
  })
})

describe('the four states of the feed', () => {
  it('shows the shape of the feed while the card is already there', async () => {
    const wrapper = mount(SubscriberView, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
        provide: {
          [apiClientKey as symbol]: {
            subscriber: vi.fn(async () => detail()),
            subscriberEvents: vi.fn(() => new Promise(() => {})),
            plans: vi.fn(async () => []),
            referralPrograms: vi.fn(async () => []),
            operate: vi.fn(),
          },
        },
        stubs: {
          RouterLink: RouterLinkStub,
          SubscriberOperations: { template: '<div />' },
          StateChip: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Loading events')
    expect(wrapper.find('h1').text()).toBe('Ada Lovelace')
  })

  it('shows the events when they arrive', async () => {
    const wrapper = await render({ events: feed([EVENT]) })

    expect(wrapper.text()).toContain('Cancelled. Access runs to 16 Oct 2026.')
    expect(wrapper.text()).toContain('1 event')
  })

  // An invitation rather than a report of emptiness: it says what would put something here.
  it('says what would fill an empty feed', async () => {
    const wrapper = await render()

    expect(wrapper.text()).toContain('Nothing has happened to this subscription yet.')
  })

  // The card survives the feed failing, which is the whole reason they are rendered separately.
  it('keeps the card when the feed fails', async () => {
    const wrapper = await render({
      events: new ApiError(500, { code: 'INTERNAL_ERROR', message: 'x', field: null }),
    })

    expect(wrapper.find('h1').text()).toBe('Ada Lovelace')
    expect(wrapper.text()).toContain('The service could not be reached.')
    expect(wrapper.text()).toContain('Try again')
  })
})
