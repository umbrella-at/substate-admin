/**
 * The audit screen: four request states, the filters, and the way back out of them.
 *
 * The two narrowings that matter here have no control of their own — a subscriber and an operator
 * are chosen by clicking a cell — so the way to clear them has to exist while they are returning
 * rows. It used to live in the empty state, which is the one place somebody who has found what
 * they were looking for never reaches.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { ApiError, type AuditEntry, type AuditPage } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import { AUDIT_ACTIONS } from '@/domain/audit'
import AuditView from '@/views/AuditView.vue'

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

function entry(over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'a-1',
    occurredAt: '2026-09-02T05:09:00Z',
    actor: { id: 'u-1', email: 'operator@example.com' },
    action: 'subscription.payment',
    targetType: 'subscription',
    targetId: 'sub-0001',
    worldId: 'base',
    outcome: 'ok',
    errorCode: null,
    payload: { amount: 500, provider: 'panel', reference: 'ref-1' },
    ...over,
  }
}

function page(items: AuditEntry[] = [entry()]): AuditPage {
  return { items, total: items.length, page: 1, pageSize: 25 }
}

const health = {
  status: 'ok',
  version: '0.0.0',
  commit: 'test',
  db: true,
  world: { id: 'base', seeded: true, subscribers: 351, events: 3791 },
}

async function render(answer: unknown = page()) {
  const wrapper = mount(AuditView, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: {
        [apiClientKey as symbol]: {
          audit: vi.fn(() =>
            answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer),
          ),
          health: vi.fn(async () => health),
        },
      },
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

function button(wrapper: Awaited<ReturnType<typeof render>>, label: string) {
  return wrapper.findAll('button').find((each) => each.text() === label)
}

beforeEach(() => {
  routeQuery.value = {}
  push.mockClear()
})

describe('the four states', () => {
  it('shows the shape of the table while it is loading', async () => {
    const wrapper = mount(AuditView, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
        provide: {
          [apiClientKey as symbol]: {
            audit: vi.fn(() => new Promise(() => {})),
            health: vi.fn(async () => health),
          },
        },
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Loading the audit')
    // And none of the other three.
    expect(wrapper.find('tbody').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Try again')
    expect(wrapper.text()).not.toContain('Nothing has been done')
  })

  it('shows the rows when they arrive', async () => {
    const wrapper = await render()

    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('1 recorded action')
    expect(wrapper.text()).not.toContain('Try again')
  })

  // An invitation rather than a report of emptiness: it says what would put something here.
  it('says what would fill an empty audit', async () => {
    const wrapper = await render(page([]))

    expect(wrapper.text()).toContain('Open a subscriber and perform an operation')
    expect(button(wrapper, 'Clear filters')).toBeUndefined()
  })

  it('says what failed and offers the retry', async () => {
    const wrapper = await render(
      new ApiError(403, {
        code: 'PERMISSION_DENIED',
        message: 'You do not have permission to do that.',
        field: null,
      }),
    )

    expect(wrapper.text()).toContain('You do not have permission to do that.')
    expect(wrapper.text()).toContain('Try again')
    expect(wrapper.find('tbody').exists()).toBe(false)
  })
})

describe('the filters', () => {
  // Every action the vocabulary has, named as a person would say it rather than as the code it is
  // stored under. Counted against the vocabulary rather than against a number written twice.
  it('offers every action, and nothing else', async () => {
    const wrapper = await render()

    expect(wrapper.findAll('fieldset').at(0)?.text()).toContain('Recorded a payment')
    expect(wrapper.findAll('fieldset').at(0)?.text()).toContain('Changed what a role grants')
    expect(wrapper.findAll('label')).toHaveLength(AUDIT_ACTIONS.length)
  })

  it('offers three outcomes and no more', async () => {
    const wrapper = await render()

    const outcomes = wrapper.findAll('fieldset').at(1)?.findAll('button') ?? []
    expect(outcomes.map((each) => each.text())).toEqual(['Everything', 'Accepted', 'Refused'])
  })

  it('puts a chosen outcome in the address', async () => {
    const wrapper = await render()

    await button(wrapper, 'Refused')?.trigger('click')

    expect(push).toHaveBeenCalledWith({ query: { outcome: 'refused' } })
  })

  // The finding this test exists for: both narrowings are set by clicking a cell, and the only way
  // back used to be inside the empty state.
  it('offers a way out of a filter that is returning rows', async () => {
    routeQuery.value = { targetId: 'sub-0001' }
    const wrapper = await render()

    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('Narrowed to')
    await button(wrapper, 'Clear filters')?.trigger('click')

    expect(push).toHaveBeenCalledWith({ query: {} })
  })

  it('blames the filters rather than the log when a narrowed page is empty', async () => {
    routeQuery.value = { targetId: 'nobody' }
    const wrapper = await render(page([]))

    expect(wrapper.text()).toContain('No recorded action matches these filters.')
    expect(wrapper.text()).not.toContain('Open a subscriber and perform an operation')
  })
})

describe('a row that outlives its world', () => {
  it('links a row about the world on screen', async () => {
    const wrapper = await render()

    expect(wrapper.findAllComponents(RouterLinkStub)).toHaveLength(1)
  })

  it('does not link a row from another world', async () => {
    const wrapper = await render(page([entry({ worldId: 'a-sandbox' })]))

    expect(wrapper.findAllComponents(RouterLinkStub)).toHaveLength(0)
    expect(wrapper.text()).toContain('sub-0001')
  })
})
