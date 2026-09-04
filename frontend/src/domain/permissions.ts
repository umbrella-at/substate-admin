/**
 * Permission codes, written by hand rather than generated.
 *
 * The backend publishes them as `string[]` because the set is data, held in the database, and a
 * role editor can change who holds which. But the codes a route or a component ASKS for are
 * finite and known at build time, so naming them here turns `permission: 'users.raed'` from a
 * silent 403 at runtime into a type error before the file is saved.
 */

export const PERMISSIONS = [
  'subscribers.read',
  'subscribers.write',
  'plans.read',
  'plans.write',
  'promo.read',
  'promo.write',
  'referrals.read',
  'referrals.write',
  'analytics.read',
  'audit.read',
  'users.read',
  'users.write',
  'demo.control',
] as const

export type PermissionCode = (typeof PERMISSIONS)[number]

/** Whether the set the server granted contains a code the interface asks for. One rule, and the
 *  store's `can` is its only caller — the guard and every component ask through that. */
export function granted(held: ReadonlySet<string>, needed: PermissionCode): boolean {
  return held.has(needed)
}
