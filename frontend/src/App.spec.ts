/**
 * The frame, and the answer at an address a role does not open. The guard marks the route rather
 * than redirecting; this is the half that reads the mark, and it was written by nothing before.
 */

import { mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h, ref } from 'vue'

import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'

const meta = ref<Record<string, unknown>>({})
const name = ref<string>('audit')

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({
    get meta() {
      return meta.value
    },
    get name() {
      return name.value
    },
  }),
  RouterView: { render: () => h('main', 'the page itself') },
}))

function render() {
  return mount(App, { global: { stubs: { RouterLink: RouterLinkStub, ClockControl: true } } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(useAuthStore(), 'can').mockReturnValue(true)
  meta.value = {}
  name.value = 'audit'
})

describe('a route the guard refused', () => {
  it('answers at the address instead of showing an empty frame', () => {
    meta.value = { forbidden: true, permission: 'audit.read' }
    const view = render()

    expect(view.text()).toContain('This page is not yours to open.')
    expect(view.text()).not.toContain('the page itself')
  })

  // Named, because the way out is somebody granting it and a person cannot ask for a thing they
  // have not been told the name of.
  it('names the permission it is behind', () => {
    meta.value = { forbidden: true, permission: 'audit.read' }
    expect(render().text()).toContain('audit.read')
  })

  it('keeps the sidebar, because the session is fine and only this page is not', () => {
    meta.value = { forbidden: true, permission: 'audit.read' }
    expect(render().text()).toContain('Subscribers')
  })
})

describe('a route the guard allowed', () => {
  it('shows the page', () => {
    meta.value = { forbidden: false, permission: 'audit.read' }
    const view = render()

    expect(view.text()).toContain('the page itself')
    expect(view.text()).not.toContain('This page is not yours to open.')
  })

  // The guard sets the mark on every navigation, but a route reached before it ran has neither
  // value. Absent must mean allowed, or the first paint of every page is a refusal.
  it('shows the page when the mark has not been set at all', () => {
    meta.value = {}
    expect(render().text()).toContain('the page itself')
  })
})

describe('the frame', () => {
  it('is not drawn around the login page', () => {
    meta.value = { requiresAuth: false }
    name.value = 'login'
    expect(render().text()).not.toContain('Subscribers')
  })
})
