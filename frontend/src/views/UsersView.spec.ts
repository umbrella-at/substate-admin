/**
 * The roles screen, and the half of the permission rule that lives in the DOM. The other half is
 * the endpoint's 403, which the browser test asserts against the running service.
 */

/* A control nobody may press is not drawn, rather than drawn and disabled: the second is an
   invitation to a locked door, and the endpoint refuses it either way. */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type MeResponse, type RolesResponse, type UserListResponse } from '@/api/client'
import { apiClientKey } from '@/api/provide'
import { TooltipProvider } from '@/components/ui/tooltip'
import UsersView from '@/views/UsersView.vue'
import { useAuthStore } from '@/stores/auth'
import { h } from 'vue'

const USERS: UserListResponse = {
  items: [
    {
      id: 'u-1',
      email: 'ada@example.com',
      isActive: true,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: null,
      role: { code: 'admin', name: 'Administrator' },
    },
  ],
  total: 1,
  page: 1,
  pageSize: 25,
}

const ROLES: RolesResponse = {
  items: [
    {
      id: 'r-admin',
      code: 'admin',
      name: 'Administrator',
      isSystem: true,
      permissions: ['users.read', 'users.write'],
      holders: 1,
    },
    {
      id: 'r-analysts',
      code: 'analysts',
      name: 'Analysts',
      isSystem: false,
      permissions: ['analytics.read'],
      holders: 0,
    },
  ],
  permissions: [
    { code: 'analytics.read', description: 'View aggregate analytics.' },
    { code: 'users.read', description: "View the panel's own users and roles." },
    { code: 'users.write', description: "Create, modify and deactivate the panel's own users." },
  ],
}

function me(permissions: string[]): MeResponse {
  return {
    user: {
      id: 'u-1',
      email: 'ada@example.com',
      isActive: true,
      createdAt: '2026-01-01T00:00:00Z',
      lastLoginAt: null,
    },
    role: { code: 'admin', name: 'Administrator' },
    permissions,
    kind: 'user',
    worldId: null,
  }
}

type Answers = {
  users?: () => Promise<unknown>
  roles?: () => Promise<unknown>
  holds?: string[]
  /** What `/auth/me` answers from now on. The operator may have just edited the role they hold. */
  holdsAfterWrite?: string[]
}

function render(over: Answers = {}) {
  useAuthStore().adopt(me(over.holds ?? ['users.read', 'users.write']))
  const client = {
    users: over.users ?? (() => Promise.resolve(USERS)),
    roles: over.roles ?? (() => Promise.resolve(ROLES)),
    replaceRole: vi.fn(() => Promise.resolve(ROLES.items[1]!)),
    deleteRole: vi.fn(() => Promise.resolve(null)),
    createRole: vi.fn(() => Promise.resolve(ROLES.items[1]!)),
    me: vi.fn(() =>
      Promise.resolve(me(over.holdsAfterWrite ?? over.holds ?? ['users.read', 'users.write'])),
    ),
  }
  return mount(TooltipProvider, {
    slots: { default: () => h(UsersView) },
    global: {
      plugins: [
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      provide: { [apiClientKey as symbol]: client },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

/** The custom role. The first in the list is a system role, whose Save and Delete are hidden from
 *  everybody — so an assertion about a permission has to be made somewhere they could appear. */
async function selectAnalysts(view: ReturnType<typeof render>): Promise<void> {
  await view
    .findAll('button')
    .find((each) => each.text() === 'Analysts')!
    .trigger('click')
}

describe('the screen', () => {
  it('lists the operators and the roles side by side', async () => {
    const view = render()
    await flushPromises()

    expect(view.text()).toContain('ada@example.com')
    expect(view.text()).toContain('Administrator')
    expect(view.text()).toContain('Analysts')
  })

  it('offers the catalogue with a sentence for every permission', async () => {
    const view = render()
    await flushPromises()

    expect(view.text()).toContain('View aggregate analytics.')
    expect(view.text()).toContain('analytics.read')
  })

  it('says why a system role cannot be edited, where the buttons would be', async () => {
    const view = render()
    await flushPromises()

    expect(view.text()).toContain('restored on every deploy')
    expect(view.text()).not.toContain('Save role')
  })
})

/**
 * The DOM half of the rule the browser test asserts both halves of. An operator who may read the
 * roles and not write them gets the screen, the catalogue, and no way to press anything.
 */
describe('an operator who may read but not write', () => {
  const READ_ONLY = { holds: ['users.read'] }

  // ON THE CUSTOM ROLE, because a system role hides Save and Delete from everybody. Asserted on
  // the system role instead, this passes with the permission check deleted.
  it('is offered no control that would be refused', async () => {
    const view = render(READ_ONLY)
    await flushPromises()
    await selectAnalysts(view)

    for (const control of ['New role', 'Save role', 'Delete role', 'Create role']) {
      expect(view.text(), control).not.toContain(control)
    }
  })

  it('still sees the roles and what they grant', async () => {
    const view = render(READ_ONLY)
    await flushPromises()

    expect(view.text()).toContain('Analysts')
    expect(view.text()).toContain('View aggregate analytics.')
  })

  it('is offered them once the permission is held', async () => {
    const view = render()
    await flushPromises()
    await selectAnalysts(view)

    expect(view.text()).toContain('Save role')
    expect(view.text()).toContain('New role')
  })
})

describe('the four states of the roles panel', () => {
  it('shows a placeholder before the first answer', () => {
    const view = render({ roles: () => new Promise(() => {}) })
    expect(view.find('.skeleton').exists()).toBe(true)
    expect(view.text()).not.toContain('Analysts')
  })

  it('offers a retry when the request fails', async () => {
    const view = render({ roles: () => Promise.reject(new ApiError(500, null)) })
    await flushPromises()
    expect(view.text()).toContain('The service could not be reached.')
    expect(view.text()).toContain('Try again')
    expect(view.text()).not.toContain('Analysts')
  })

  it('says what would put an operator in the list when there is none', async () => {
    const view = render({ users: () => Promise.resolve({ ...USERS, items: [], total: 0 }) })
    await flushPromises()
    expect(view.text()).toContain('The command line creates the first one.')
  })

  it('shows the roles once they arrive', async () => {
    const view = render()
    await flushPromises()
    expect(view.find('.skeleton').exists()).toBe(false)
    expect(view.text()).toContain('Analysts')
  })
})

/**
 * An operator may edit the role they hold, and the store is what the nav, the guard and every
 * write control decide from. Invalidating a cache entry nothing on this screen observes refetched
 * nothing, so the panel went on drawing controls the server had just started refusing.
 */
describe('editing the role you hold yourself', () => {
  it('takes the new permissions from the server rather than keeping the old ones', async () => {
    const view = render({ holdsAfterWrite: ['users.read'] })
    await flushPromises()
    await selectAnalysts(view)
    expect(view.text()).toContain('Save role')

    await view.findAll('input[type="checkbox"], button[role="checkbox"]').at(0)!.trigger('click')
    await view
      .findAll('button')
      .find((each) => each.text().startsWith('Save role'))!
      .trigger('click')
    await flushPromises()
    await flushPromises()

    expect([...useAuthStore().permissions]).toEqual(['users.read'])
    expect(view.text()).not.toContain('Save role')
    expect(view.text()).not.toContain('New role')
  })
})
