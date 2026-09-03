/**
 * What the roles screen edits. `changed` is what Save is enabled by, so a press that would send
 * the role back exactly as it arrived is not offered as though it would do something.
 */

import { describe, expect, it } from 'vitest'

import type { PermissionSummary, RoleDetail } from '@/api/client'
import { bySubject, changed, draftOf, roleForm, subjectLabel, whyItCannotGo } from '@/domain/roles'

function role(over: Partial<RoleDetail> = {}): RoleDetail {
  return {
    id: 'r-1',
    code: 'analysts',
    name: 'Analysts',
    isSystem: false,
    permissions: ['analytics.read', 'subscribers.read'],
    holders: 0,
    ...over,
  }
}

function permission(code: string): PermissionSummary {
  return { code, description: `What ${code} allows.` }
}

describe('the new-role form', () => {
  it('accepts the shape the server accepts', () => {
    expect(roleForm.safeParse({ code: 'analysts', name: 'Analysts' }).success).toBe(true)
    expect(roleForm.safeParse({ code: 'a-b_2', name: 'A' }).success).toBe(true)
  })

  // The same pattern the server enforces, so the refusal happens under the field rather than one
  // round-trip away with nothing pointing at the input that caused it.
  it('refuses a code the server would refuse', () => {
    for (const code of ['Analysts', '2fast', 'has space', 'a', 'ünicode', '']) {
      expect(roleForm.safeParse({ code, name: 'Fine' }).success, code).toBe(false)
    }
  })

  it('refuses a role with no name', () => {
    expect(roleForm.safeParse({ code: 'analysts', name: '   ' }).success).toBe(false)
  })
})

describe('whether a draft differs from its role', () => {
  it('says no to the draft it was taken from', () => {
    const each = role()
    expect(changed(each, draftOf(each))).toBe(false)
  })

  it('sees a renamed role, a granted code and a revoked one', () => {
    const each = role()
    expect(changed(each, { ...draftOf(each), name: 'Auditors' })).toBe(true)
    expect(changed(each, { name: each.name, permissions: new Set(['analytics.read']) })).toBe(true)
    expect(
      changed(each, {
        name: each.name,
        permissions: new Set([...each.permissions, 'audit.read']),
      }),
    ).toBe(true)
  })

  // A set of the same size holding different codes is the case a length check alone would miss.
  it('sees a swap that leaves the count alone', () => {
    const each = role()
    const swapped = new Set(['analytics.read', 'audit.read'])
    expect(changed(each, { name: each.name, permissions: swapped })).toBe(true)
  })

  it('ignores space around a name', () => {
    const each = role()
    expect(changed(each, { ...draftOf(each), name: '  Analysts  ' })).toBe(false)
  })
})

describe('the catalogue as the editor reads it', () => {
  it('groups the codes by what they are about, in the order they arrived', () => {
    const groups = bySubject([
      permission('subscribers.read'),
      permission('subscribers.write'),
      permission('audit.read'),
    ])
    expect(groups.map((each) => each.subject)).toEqual(['subscribers', 'audit'])
    expect(groups[0]!.codes).toHaveLength(2)
  })

  it('names a subject as a person would, and falls back to the code itself', () => {
    expect(subjectLabel('users')).toBe('Users and roles')
    expect(subjectLabel('something-new')).toBe('something-new')
  })
})

describe('why a role cannot be deleted', () => {
  // Said where the button would be, so the reason is on screen before the press rather than in
  // the refusal after it.
  it('names the deploy for a system role', () => {
    expect(whyItCannotGo(role({ isSystem: true }))).toContain('restored on every deploy')
  })

  it('counts the people holding a custom one, and agrees with its verb', () => {
    expect(whyItCannotGo(role({ holders: 1 }))).toContain('One person holds')
    expect(whyItCannotGo(role({ holders: 4 }))).toContain('4 people hold')
  })

  it('says nothing about a custom role nobody holds', () => {
    expect(whyItCannotGo(role())).toBeNull()
  })
})
