/**
 * The navigation offers what the visitor may actually open.
 *
 * A link to a page the router will refuse is an invitation to a locked door: the visitor clicks,
 * is bounced, and learns that the panel is unreliable rather than that they lack a permission.
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { apiClientKey } from '@/api/provide'
import AppShell from '@/components/AppShell.vue'
import { useAuthStore } from '@/stores/auth'

const routeName = ref<string>('dashboard')

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({
    get name() {
      return routeName.value
    },
  }),
}))

/** The frame reads the world's clock for every screen inside it, so mounting it needs the query
 *  plumbing and a client that can answer. What the reading says is asserted elsewhere. */
const stillThinking = { clock: () => new Promise(() => {}) }

function render() {
  return mount(AppShell, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      provide: { [apiClientKey as unknown as string]: stillThinking },
      stubs: { RouterLink: RouterLinkStub, ClockControl: true },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  routeName.value = 'dashboard'
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
