/**
 * The screen a demonstration ends on. It exists because the login page's sentence — "sign in again
 * to carry on where you were" — is advice a visitor cannot take: there was never an account, and
 * the address they were on belongs to a world that is gone.
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub } from '@vue/test-utils'

import { ApiError, type DemoSession, type MeResponse } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import DemoEndedView from '@/views/DemoEndedView.vue'

const replace = vi.fn()

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRouter: () => ({ replace }),
}))

const ME: MeResponse = {
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
}

function stubClient(overrides: Record<string, unknown> = {}) {
  return {
    demoSession: vi.fn<() => Promise<DemoSession>>().mockResolvedValue({
      accessToken: 'a-new-pass',
      expiresIn: 3600,
      endsAt: '2026-09-04T14:00:00Z',
    }),
    me: vi.fn<() => Promise<MeResponse>>().mockResolvedValue(ME),
    setDemoToken: vi.fn(),
    ...overrides,
  }
}

async function open(client: ReturnType<typeof stubClient>) {
  const wrapper = mount(DemoEndedView, {
    global: {
      plugins: [createPinia()],
      provide: { [apiClientKey as unknown as string]: client },
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  await wrapper.find('button').trigger('click')
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  replace.mockReset()
})

describe('after a demonstration ends', () => {
  it('says what happened without blaming the session', async () => {
    const wrapper = mount(DemoEndedView, {
      global: {
        plugins: [createPinia()],
        provide: { [apiClientKey as unknown as string]: stubClient() },
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(wrapper.text()).toContain('That demonstration has ended.')
    // Not "your session expired": there was no session to expire, and telling somebody to sign in
    // again is telling them to use credentials they were never given.
    expect(wrapper.text()).not.toContain('Sign in again')
  })

  it('starts another and goes into it', async () => {
    const client = stubClient()

    await open(client)

    expect(client.setDemoToken).toHaveBeenCalledWith('a-new-pass')
    expect(client.me).toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith({ name: 'dashboard' })
  })

  // The service's own sentence, because it knows which of the four happened and this screen does
  // not. It used to collapse them into one boolean and then assert one of them.
  it('repeats why no world could be had, rather than guessing', async () => {
    const client = stubClient({
      demoSession: vi.fn().mockRejectedValue(
        new ApiError(503, {
          code: 'SANDBOX_FULL',
          message: 'Every demonstration slot is in use just now.',
          field: null,
        } as never),
      ),
    })

    const wrapper = await open(client)

    expect(wrapper.text()).toContain('Every demonstration slot is in use just now.')
    expect(replace).not.toHaveBeenCalledWith({ name: 'dashboard' })
  })

  // And the one cause the service cannot describe, because it did not answer. Told apart from the
  // one above, which is the whole point: "every slot is taken" is a different fact from silence.
  it("does not put a busy service's words on a service that never answered", async () => {
    const client = stubClient({
      demoSession: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    })

    const wrapper = await open(client)

    expect(wrapper.text()).toContain('The service did not answer')
    expect(wrapper.text()).not.toContain('slot')
  })

  // Decision 205: one button. The second exit went to the login page, which is the destination
  // this whole screen exists to avoid.
  it('offers no way to the sign-in page', async () => {
    const wrapper = mount(DemoEndedView, {
      global: {
        plugins: [createPinia()],
        provide: { [apiClientKey as unknown as string]: stubClient() },
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(wrapper.findAllComponents(RouterLinkStub)).toHaveLength(0)
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})
