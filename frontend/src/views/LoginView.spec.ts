/**
 * What this page is allowed to say.
 *
 * The backend spends real effort making its three login failures indistinguishable: a dummy argon2
 * verification when the address does not exist, the `is_active` check placed AFTER the password
 * check so a disabled account costs the same milliseconds as a live one. None of that survives a
 * frontend that words them differently, and nothing about the frontend's own types would catch it
 * — which is exactly why it is asserted here.
 *
 * The other assertion worth having is the negative one: an unreachable service must never be
 * reported as a wrong password. That is the failure that makes someone change a correct password.
 */

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type MeResponse, type TokenResponse } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import LoginView from '@/views/LoginView.vue'

const replace = vi.fn()

vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRouter: () => ({ replace }),
  useRoute: () => ({ query: {} }),
}))

function apiError(status: number, code: string, message: string): ApiError {
  return new ApiError(status, { code, message } as never)
}

const ME: MeResponse = {
  kind: 'user',
  permissions: ['users.read'],
  role: { code: 'admin', name: 'Administrator' },
  user: {
    createdAt: '2026-01-01T00:00:00Z',
    email: 'operator@example.com',
    id: '00000000-0000-0000-0000-000000000000',
    isActive: true,
    lastLoginAt: null,
  },
}

function stubClient(overrides: Partial<Record<'login' | 'me', unknown>> = {}) {
  return {
    login: vi.fn<() => Promise<TokenResponse>>(),
    me: vi.fn<() => Promise<MeResponse>>().mockResolvedValue(ME),
    setAccessToken: vi.fn(),
    ...overrides,
  }
}

async function signIn(client: ReturnType<typeof stubClient>) {
  const wrapper = mount(LoginView, {
    global: {
      plugins: [createPinia()],
      provide: { [apiClientKey as unknown as string]: client },
    },
  })
  const inputs = wrapper.findAll('input')
  await inputs[0]?.setValue('operator@example.com')
  await inputs[1]?.setValue('correct horse battery staple')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  replace.mockReset()
})

describe('the sentence a refusal produces', () => {
  it('says the same thing for every 401, even one whose body leaks the reason', async () => {
    // The middle two bodies are what a REGRESSION on the server looks like: a 401 that has started
    // distinguishing the three cases in its message. The page must not become the place that
    // difference reaches the screen, so it derives the sentence from the status and never from the
    // text it was handed.
    const leaky: [string, string][] = [
      ['INVALID_CREDENTIALS', 'Email or password is incorrect.'],
      ['INVALID_CREDENTIALS', 'No account exists for that address.'],
      ['USER_INACTIVE', 'This account is disabled.'],
    ]

    const said = new Set<string>()
    for (const [code, message] of leaky) {
      const client = stubClient({ login: vi.fn().mockRejectedValue(apiError(401, code, message)) })
      const wrapper = await signIn(client)
      said.add(wrapper.find('[role="alert"]').text())
    }

    expect([...said]).toEqual(['Email or password is incorrect.'])
  })

  it('does not blame the password when the service was never reached', async () => {
    const client = stubClient({
      login: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    })
    const wrapper = await signIn(client)
    const text = wrapper.find('[role="alert"]').text()
    expect(text).toContain('could not be reached')
    expect(text).not.toContain('incorrect')
  })

  it('does not blame the password for a 500 either', async () => {
    const client = stubClient({
      login: vi
        .fn()
        .mockRejectedValue(apiError(500, 'INTERNAL_ERROR', 'Something went wrong. Try again.')),
    })
    const wrapper = await signIn(client)
    const text = wrapper.find('[role="alert"]').text()
    expect(text).toContain('could not be reached')
    // The API's own 500 sentence is the one docs/design.md forbids, so it must not be echoed.
    expect(text).not.toContain('Something went wrong')
  })

  it('gives being rate limited its own sentence, and says that waiting helps', async () => {
    const client = stubClient({
      login: vi
        .fn()
        .mockRejectedValue(
          apiError(429, 'RATE_LIMITED', 'Too many attempts. Try again in a few minutes.'),
        ),
    })
    const wrapper = await signIn(client)
    const text = wrapper.find('[role="alert"]').text()
    expect(text).toContain('Too many attempts')
    expect(text).not.toContain('incorrect')
  })

  it('points the fields at the sentence, so a screen reader is told which form it belongs to', async () => {
    const client = stubClient({
      login: vi
        .fn()
        .mockRejectedValue(apiError(401, 'INVALID_CREDENTIALS', 'Email or password is incorrect.')),
    })
    const wrapper = await signIn(client)
    const id = wrapper.find('[role="alert"]').attributes('id')
    expect(id).toBeTruthy()
    for (const input of wrapper.findAll('input')) {
      expect(input.attributes('aria-describedby')).toBe(id)
    }
  })

  it('marks the fields invalid for a bad password but not for an unreachable service', async () => {
    const refused = await signIn(
      stubClient({
        login: vi
          .fn()
          .mockRejectedValue(
            apiError(401, 'INVALID_CREDENTIALS', 'Email or password is incorrect.'),
          ),
      }),
    )
    expect(refused.findAll('input')[0]?.attributes('aria-invalid')).toBe('true')

    const offline = await signIn(
      stubClient({ login: vi.fn().mockRejectedValue(new TypeError('Failed to fetch')) }),
    )
    expect(offline.findAll('input')[0]?.attributes('aria-invalid')).toBeUndefined()
  })
})

describe('while the request is in flight', () => {
  it('refuses the second submit, keeps its colours and changes only the label', async () => {
    // Never resolves: the button stays in flight for the whole test.
    const client = stubClient({ login: vi.fn().mockReturnValue(new Promise(() => {})) })
    const wrapper = await signIn(client)

    const button = wrapper.find('button')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.text()).toBe('Signing in…')
    // The colours are the accent fill, exactly as they were before the click.
    expect(button.classes()).toContain('bg-accent-fill')
    expect(button.classes()).not.toContain('bg-fill-disabled')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(client.login).toHaveBeenCalledTimes(1)
  })
})

describe('an empty form', () => {
  it('is answered without spending an attempt on the login limiter', async () => {
    const client = stubClient()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [createPinia()],
        provide: { [apiClientKey as unknown as string]: client },
      },
    })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(client.login).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').text()).toContain('Enter your email address')
  })
})

describe('after a successful sign-in', () => {
  it('adopts the session and goes to the dashboard', async () => {
    const client = stubClient({
      login: vi.fn().mockResolvedValue({ accessToken: 'token', expiresIn: 900 }),
    })
    await signIn(client)
    expect(client.setAccessToken).toHaveBeenCalledWith('token')
    expect(client.me).toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith('/')
  })
})
