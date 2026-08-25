/**
 * The union is a copy, and this file checks the half of it that can be checked from here.
 *
 * `PermissionCode` is written by hand for a good reason — the backend publishes permissions as
 * `string[]` because the grants are data, while the codes the interface ASKS for are finite and
 * known at build time — but hand-written means it can drift from
 * `backend/app/permissions.py`, which is the actual source of truth (`sync-permissions` force-
 * syncs the database to it on every deploy).
 *
 * That comparison is NOT made here, and deliberately not: reading a file outside `frontend/`
 * needs either node's types, which `tsconfig.app.json` keeps out of the application project on
 * purpose, or Vite's `?raw`, which its `server.fs.allow` refuses to serve from above the Vite
 * root. Both would be a test bending the project's boundaries to fit itself. The check belongs to
 * CI, where the two files are already both on disk — see the report accompanying this suite.
 *
 * What is left is still worth asserting: the catalogue names each code once, the union is closed,
 * and `granted` is a membership test and nothing cleverer than one.
 */

import { describe, expect, it } from 'vitest'

import { granted, PERMISSIONS, type PermissionCode } from './permissions'

describe('granted', () => {
  it('answers for the exact code and for no other', () => {
    const held = new Set<string>(['subscribers.read', 'audit.read'])

    expect(granted(held, 'subscribers.read')).toBe(true)
    expect(granted(held, 'audit.read')).toBe(true)
    // Read is not write, and the shared prefix must not become a shared grant. This is the whole
    // reason the check is a set membership rather than anything cleverer.
    expect(granted(held, 'subscribers.write')).toBe(false)
    expect(granted(held, 'users.read')).toBe(false)
  })

  it('grants nothing at all to a role that has been given nothing', () => {
    // Not hypothetical: a role with no permissions yet is an ordinary row in the roles table, and
    // the person holding it can sign in perfectly well.
    const none = new Set<string>()
    for (const code of PERMISSIONS) expect(granted(none, code)).toBe(false)
  })

  it('is not fooled by a code that merely starts the same way', () => {
    expect(granted(new Set(['users.readonly']), 'users.read')).toBe(false)
    expect(granted(new Set(['users']), 'users.read')).toBe(false)
  })

  it('refuses a code the union does not contain, before the code is ever run', () => {
    // @ts-expect-error a typo must be a type error here rather than a 403 nobody sees until a
    // reviewer clicks the wrong tab.
    granted(new Set<string>(), 'users.raed')
    // @ts-expect-error a permission the backend does not define is not a permission.
    granted(new Set<string>(), 'subscribers.delete')
  })
})

describe('the catalogue', () => {
  it('names each code once', () => {
    expect(new Set(PERMISSIONS).size).toBe(PERMISSIONS.length)
  })

  it('is a flat list of dotted lower-case codes, which is the shape the backend sends', () => {
    // The permissions arrive as plain strings on `/auth/me` and are compared by equality. A code
    // with a capital or a space in it would be one this interface can never match.
    for (const code of PERMISSIONS) expect(code).toMatch(/^[a-z]+\.[a-z]+$/)
  })
})

describe('the type', () => {
  it('is exactly the values of the array, so the two cannot disagree', () => {
    // A compile-time assertion with a runtime body: if `PermissionCode` were ever widened to
    // `string`, the annotation below would still hold but the assignment after it would not fail
    // — which is why the second half is here.
    const code: PermissionCode = 'demo.control'
    expect(PERMISSIONS).toContain(code)

    // @ts-expect-error the union is closed; a plain string is not a permission code.
    const widened: PermissionCode = 'anything at all'
    expect(PERMISSIONS).not.toContain(widened)
  })
})
