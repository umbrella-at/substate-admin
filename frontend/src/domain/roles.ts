/**
 * What the roles screen edits, and the form it edits through. The catalogue arrives with the
 * roles, so a checkbox cannot be offered for a permission the server has never heard of.
 */

import { z } from 'zod'

import type { PermissionSummary, RoleDetail } from '@/api/client'

/** The two fields a role's own code may be spelled with, matching the server's pattern exactly.
 *  A form that accepted more would push the refusal one round-trip further away. */
export const CODE = /^[a-z][a-z0-9_-]*$/

export const roleForm = z.object({
  code: z
    .string()
    .trim()
    .min(2, 'A code is at least two characters.')
    .max(40, 'A code is at most forty characters.')
    .regex(CODE, 'Lower case, starting with a letter: digits, - and _ after that.'),
  name: z
    .string()
    .trim()
    .min(1, 'A role needs a name people will recognise.')
    .max(80, 'A name is at most eighty characters.'),
})

export type RoleForm = z.infer<typeof roleForm>

export interface Draft {
  name: string
  permissions: Set<string>
}

export function draftOf(role: RoleDetail): Draft {
  return { name: role.name, permissions: new Set(role.permissions) }
}

/** Whether a draft differs from the role it was taken from. What Save is enabled by, so a press
 *  that would change nothing is not offered as though it would. */
export function changed(role: RoleDetail, draft: Draft): boolean {
  if (draft.name.trim() !== role.name) return true
  if (draft.permissions.size !== role.permissions.length) return true
  return role.permissions.some((code) => !draft.permissions.has(code))
}

/** The catalogue split by its own prefix, so the editor reads as the subjects it grants over
 *  rather than as thirteen unrelated lines. */
export function bySubject(
  permissions: readonly PermissionSummary[],
): { subject: string; codes: PermissionSummary[] }[] {
  const groups = new Map<string, PermissionSummary[]>()
  for (const permission of permissions) {
    const subject = permission.code.split('.')[0] ?? permission.code
    groups.set(subject, [...(groups.get(subject) ?? []), permission])
  }
  return [...groups].map(([subject, codes]) => ({ subject, codes }))
}

const SUBJECT_LABEL: Record<string, string> = {
  subscribers: 'Subscribers',
  plans: 'Plans',
  promo: 'Promo codes',
  referrals: 'Referrals',
  analytics: 'Analytics',
  audit: 'Audit',
  users: 'Users and roles',
  demo: 'Demonstration',
}

export function subjectLabel(subject: string): string {
  return SUBJECT_LABEL[subject] ?? subject
}

/** Said where the delete button would be, so the reason is on screen before the press rather
 *  than in the refusal after it. */
export function whyItCannotGo(role: RoleDetail): string | null {
  if (role.isSystem) {
    return 'This role is defined by the application and restored on every deploy. Copy it into a role of your own to change it.'
  }
  if (role.holders > 0) {
    return `${role.holders === 1 ? 'One person holds' : `${role.holders} people hold`} this role. Move them to another one, and it can be deleted.`
  }
  return null
}
