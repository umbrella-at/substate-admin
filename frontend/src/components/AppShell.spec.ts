/**
 * The navigation offers what the visitor may actually open.
 *
 * A link to a page the router will refuse is an invitation to a locked door: the visitor clicks,
 * is bounced, and learns that the panel is unreliable rather than that they lack a permission.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { apiClientKey } from '@/api/provide'
import AppShell from '@/components/AppShell.vue'
import { useAuthStore } from '@/stores/auth'

const routeName = ref<string>('dashboard')
const replace = vi.fn()

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({
    get name() {
      return routeName.value
    },
  }),
  useRouter: () => ({ replace }),
}))

/** The frame reads the world's clock for every screen inside it, so mounting it needs the query
 *  plumbing and a client that can answer. What the reading says is asserted elsewhere. */
const asked = vi.fn(() => new Promise(() => {}))
const stillThinking = { clock: asked }

function render(client: unknown = stillThinking) {
  return mount(AppShell, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: { [apiClientKey as unknown as string]: client },
      stubs: { RouterLink: RouterLinkStub, ClockControl: true },
    },
  })
}

/** A session, because every query mounted in the frame is guarded on one. */
function signIn(code: string) {
  const auth = useAuthStore()
  auth.adopt({
    kind: 'user',
    permissions: [],
    role: { code, name: code },
    user: {
      createdAt: '2026-01-01T00:00:00Z',
      email: `${code}@example.com`,
      id: '00000000-0000-0000-0000-000000000000',
      isActive: true,
      lastLoginAt: null,
    },
  })
  return auth
}

beforeEach(() => {
  setActivePinia(createPinia())
  routeName.value = 'dashboard'
  replace.mockClear()
})

describe('the sidebar', () => {
  it('hides a section the visitor may not open', () => {
    const auth = useAuthStore()
    vi.spyOn(auth, 'can').mockReturnValue(false)
    expect(render().text()).not.toContain('Subscribers')
  })

  it('offers it once they hold the permission', () => {
    const auth = useAuthStore()
    vi.spyOn(auth, 'can').mockReturnValue(true)
    expect(render().text()).toContain('Subscribers')
  })

  // The highlight is the visible half of this; a screen reader gets the other half.
  it('says which section is being looked at', () => {
    const auth = useAuthStore()
    vi.spyOn(auth, 'can').mockReturnValue(true)
    routeName.value = 'subscribers'
    const links = render().findAllComponents(RouterLinkStub)
    expect(links.at(0)?.attributes('aria-current')).toBeUndefined()
    expect(links.at(1)?.attributes('aria-current')).toBe('page')
  })
})

describe('the world the frame is showing', () => {
  it('asks what time it is there, whoever is looking', () => {
    // The clock control is drawn only for whoever may press it, and `support` and `viewer` never
    // hold `demo.control` — so a frame that read the clock only through the control would leave
    // them measuring every relative time against their own browser on a world somebody wound.
    const auth = useAuthStore()
    // A session, because the query is guarded on one — every query mounted in the frame is, so
    // that a teardown's refetch cannot turn a deliberate ending into a session-expired banner.
    auth.adopt({
      kind: 'user',
      permissions: [],
      role: { code: 'viewer', name: 'Viewer' },
      user: {
        createdAt: '2026-01-01T00:00:00Z',
        email: 'viewer@example.com',
        id: '00000000-0000-0000-0000-000000000000',
        isActive: true,
        lastLoginAt: null,
      },
    })
    vi.spyOn(auth, 'can').mockReturnValue(false)
    asked.mockClear()

    render()

    expect(asked).toHaveBeenCalled()
  })

  // Said in the frame for the same reason it is read there. The sentence used to live inside the
  // control, so the two roles that cannot see the control were the two that got no warning at all
  // — and they are the ones whose every relative time would quietly be measured against Chrome.
  it('says so to somebody who cannot see the clock control', async () => {
    const auth = signIn('viewer')
    vi.spyOn(auth, 'can').mockReturnValue(false)

    const wrapper = render({
      clock: vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    await flushPromises()

    expect(wrapper.text()).toContain("This world's clock could not be read")
    expect(wrapper.text()).toContain('Try again')
  })

  it('says nothing when the reading arrives', async () => {
    const auth = signIn('viewer')
    vi.spyOn(auth, 'can').mockReturnValue(false)

    const wrapper = render({
      clock: vi.fn(async () => ({
        now: '2026-09-06T00:00:00Z',
        offsetSeconds: 0,
        isSandbox: false,
        daysLeft: 365,
      })),
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain("This world's clock could not be read")
  })
})

/**
 * The way out lives in the frame, because the frame is on every screen. It used to be a button on
 * the dashboard, so leaving from the subscriber table meant navigating to the dashboard first.
 */
describe('signing out', () => {
  function withSession() {
    const auth = signIn('admin')
    vi.spyOn(auth, 'can').mockReturnValue(true)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const client = {
      clock: vi.fn(() => new Promise(() => {})),
      logout: vi.fn(async () => undefined),
      setAccessToken: vi.fn(),
    }
    const wrapper = mount(AppShell, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient }]],
        provide: { [apiClientKey as unknown as string]: client },
        stubs: { RouterLink: RouterLinkStub, ClockControl: true },
      },
    })
    return { wrapper, client, queryClient, auth }
  }

  function theButton(wrapper: ReturnType<typeof mount>) {
    return wrapper.findAll('button').find((each) => each.text().startsWith('Sign out'))
  }

  it('is offered from every screen, not from one of them', () => {
    const { wrapper } = withSession()
    routeName.value = 'subscribers'
    expect(theButton(wrapper)).toBeDefined()
  })

  it('is not the loudest control in the frame', () => {
    const { wrapper } = withSession()
    for (const button of wrapper.findAll('button')) {
      expect(button.classes()).not.toContain('bg-accent-fill')
    }
  })

  it('empties the query cache, so the next person cannot be shown this one', async () => {
    const { wrapper, client, queryClient } = withSession()
    queryClient.setQueryData(['auth', 'me'], { anything: true })

    await theButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(client.logout).toHaveBeenCalled()
    expect(client.setAccessToken).toHaveBeenCalledWith(null)
    expect(queryClient.getQueryData(['auth', 'me'])).toBeUndefined()
    expect(useAuthStore().isAuthenticated).toBe(false)
    expect(replace).toHaveBeenCalledWith({ name: 'login' })
  })

  // Refusing to sign out because the network is down would leave somebody signed in on a machine
  // they are walking away from.
  it('still ends the session locally when the server cannot be told', async () => {
    const { wrapper, client, queryClient } = withSession()
    queryClient.setQueryData(['auth', 'me'], { anything: true })
    client.logout.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await theButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(useAuthStore().isAuthenticated).toBe(false)
    expect(queryClient.getQueryData(['auth', 'me'])).toBeUndefined()
    expect(replace).toHaveBeenCalledWith({ name: 'login' })
  })
})
