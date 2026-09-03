/**
 * One role's editor, and the watch that decides when a draft is thrown away. Resetting on every
 * arrival of the prop discarded any tick made while the save was still in flight — the refetch
 * that follows a save hands the same role back as a new object.
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { PermissionSummary, RoleDetail } from '@/api/client'
import RoleEditor from '@/components/RoleEditor.vue'

const CATALOGUE: PermissionSummary[] = [
  { code: 'analytics.read', description: 'View aggregate analytics.' },
  { code: 'audit.read', description: 'Read the record of administrative actions.' },
]

function role(over: Partial<RoleDetail> = {}): RoleDetail {
  return {
    id: 'r-analysts',
    code: 'analysts',
    name: 'Analysts',
    isSystem: false,
    permissions: ['analytics.read'],
    holders: 0,
    ...over,
  }
}

interface Over {
  role?: RoleDetail
  mayWrite?: boolean
  saving?: boolean
}

/** Mounted as the root, so `setProps` can hand the same role back the way a save's refetch does. */
function render(over: Over = {}) {
  return mount(RoleEditor, {
    props: {
      role: over.role ?? role(),
      catalogue: CATALOGUE,
      mayWrite: over.mayWrite ?? true,
      saving: over.saving ?? false,
      deleting: false,
    },
  })
}

function save(view: ReturnType<typeof render>) {
  return view.findAll('button').find((each) => each.text().startsWith('Save role'))
}

describe('the draft', () => {
  it('is dirty once a permission is ticked, and clean before that', async () => {
    const view = render()
    expect(save(view)?.attributes('disabled')).toBe('')

    await view.findAll('button[role="checkbox"]').at(1)!.trigger('click')
    expect(save(view)?.attributes('disabled')).toBeUndefined()
  })

  // The same role arriving again is what a save's own refetch produces. Reset on that, and every
  // tick made during the request is gone with nothing on screen saying so.
  it('survives the same role arriving again as a new object', async () => {
    const view = render()
    await view.findAll('button[role="checkbox"]').at(1)!.trigger('click')

    await view.setProps({ role: role() })
    expect(save(view)?.attributes('disabled')).toBeUndefined()
  })

  it('is replaced when the selection moves to another role', async () => {
    const view = render()
    await view.findAll('button[role="checkbox"]').at(1)!.trigger('click')

    await view.setProps({ role: role({ id: 'r-auditors', code: 'auditors', name: 'Auditors' }) })
    expect(view.text()).toContain('Auditors')
    expect(save(view)?.attributes('disabled')).toBe('')
  })
})

describe('a role the application defines', () => {
  it('offers no way to change it, and says why where the buttons would be', () => {
    const view = render({ role: role({ isSystem: true, holders: 3 }) })

    expect(view.text()).toContain('restored on every deploy')
    expect(save(view)).toBeUndefined()
    expect(view.text()).not.toContain('Delete role')
  })

  it('draws its grants, so it can be read and copied', () => {
    const view = render({ role: role({ isSystem: true }) })
    expect(view.text()).toContain('analytics.read')
    expect(view.text()).toContain('View aggregate analytics.')
  })
})
