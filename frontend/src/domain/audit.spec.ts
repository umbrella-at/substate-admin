/**
 * The audit's question, and what a row says it was.
 *
 * The URL is the state, so the two directions have to agree: a query that survives a round trip
 * through the address bar is a link somebody can send. And `requested()` is the reason there is no
 * payload column — it renders the request as the values it was, so the column that would otherwise
 * be truncated to `{"planId": "an…` does not exist.
 */

import { describe, expect, it } from 'vitest'

import type { AuditEntry } from '@/api/client'
import {
  ACTION_LABEL,
  AUDIT_ACTIONS,
  auditQueryFromRoute,
  auditQueryToRoute,
  auditQueryToSearchParams,
  EMPTY_AUDIT_QUERY,
  hasAuditFilters,
  requested,
  type AuditQuery,
} from '@/domain/audit'

function entry(over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'a-1',
    occurredAt: '2026-09-02T05:09:00Z',
    actor: { id: 'u-1', email: 'operator@example.com' },
    action: 'subscription.cancel',
    targetType: 'subscription',
    targetId: 'sub-0001',
    worldId: 'base',
    outcome: 'ok',
    errorCode: null,
    payload: {},
    ...over,
  }
}

describe('the action vocabulary', () => {
  // Total, and stated here as well as in the type: a label record that gained an entry nobody
  // writes is a string in a file everybody reads and nobody sees on screen.
  it('has a label for every action and no others', () => {
    expect(Object.keys(ACTION_LABEL).sort()).toEqual([...AUDIT_ACTIONS].sort())
  })

  // Subscription operations first, in the order an operator reaches for them, then the role edits
  // and the clock: those are rare and are looked for on purpose rather than scanned past.
  it('offers the operations first and the rare things last', () => {
    expect([...AUDIT_ACTIONS]).toEqual([
      'subscription.payment',
      'subscription.cancel',
      'subscription.change_plan',
      'subscription.redeem',
      'subscription.subscribe',
      'subscription.assign_program',
      'role.create',
      'role.update',
      'role.delete',
      'world.advance',
    ])
  })
})

describe('what was asked for', () => {
  it.each([
    ['subscription.cancel', {}, ''],
    ['subscription.change_plan', { planId: 'annual' }, 'annual'],
    ['subscription.redeem', { promoCode: 'LAUNCH20' }, 'LAUNCH20'],
    ['subscription.assign_program', { programId: 'partners' }, 'partners'],
    ['subscription.subscribe', { planId: 'annual', promoCode: null }, 'annual'],
    ['subscription.subscribe', { planId: 'annual', promoCode: 'X' }, 'annual with X'],
    [
      'subscription.payment',
      { amount: 500, provider: 'panel', reference: 'ref-1' },
      '5.00 · ref-1',
    ],
  ] as const)('renders %s from its own payload', (action, payload, expected) => {
    expect(requested(entry({ action, payload }))).toBe(expected)
  })

  // Never the result. What happened is in the event journal, and a copy here would be two
  // journals holding two versions of one truth.
  it('says nothing about what came of it', () => {
    const refused = entry({
      action: 'subscription.redeem',
      payload: { promoCode: 'NOPE' },
      outcome: 'refused',
      errorCode: 'UNKNOWN_PROMO_CODE',
    })

    expect(requested(refused)).toBe('NOPE')
  })
})

describe('the address is the question', () => {
  it('survives a round trip through the route', () => {
    const asked: AuditQuery = {
      page: 3,
      actions: ['subscription.cancel', 'subscription.redeem'],
      outcome: 'refused',
      targetId: 'sub-0007',
      actorUserId: 'u-9',
    }

    expect(auditQueryFromRoute(auditQueryToRoute(asked))).toEqual(asked)
  })

  // Defaults are omitted so the common address stays short and two routes that mean the same
  // thing are spelled the same way.
  it('writes nothing for the question nobody narrowed', () => {
    expect(auditQueryToRoute(EMPTY_AUDIT_QUERY)).toEqual({})
  })

  it('drops an action this panel does not have', () => {
    const parsed = auditQueryFromRoute({ action: ['subscription.cancel', 'subscription.explode'] })

    expect(parsed.actions).toEqual(['subscription.cancel'])
  })

  // Two spellings of one question would be two cache entries and two requests for one answer.
  it('asks for one action once', () => {
    const parsed = auditQueryFromRoute({
      action: ['subscription.cancel', 'subscription.cancel'],
    })

    expect(parsed.actions).toEqual(['subscription.cancel'])
  })

  it.each([['0'], ['-2'], ['half'], ['']])('falls back to the first page for %s', (page) => {
    expect(auditQueryFromRoute({ page }).page).toBe(1)
  })

  it('always sends the page, and only the narrowings that exist', () => {
    const params = auditQueryToSearchParams({ ...EMPTY_AUDIT_QUERY, outcome: 'ok' })

    expect([...params.keys()].sort()).toEqual(['outcome', 'page'])
  })

  it.each([
    ['nothing', EMPTY_AUDIT_QUERY, false],
    ['an action', { ...EMPTY_AUDIT_QUERY, actions: ['subscription.cancel'] as const }, true],
    ['an outcome', { ...EMPTY_AUDIT_QUERY, outcome: 'ok' as const }, true],
    ['a subscriber', { ...EMPTY_AUDIT_QUERY, targetId: 'sub-1' }, true],
    ['an operator', { ...EMPTY_AUDIT_QUERY, actorUserId: 'u-1' }, true],
  ])('knows a question narrowed by %s', (_name, query, narrowed) => {
    expect(hasAuditFilters(query as AuditQuery)).toBe(narrowed)
  })
})

/** Decision 220 left this undone and the estimate was pessimistic: `target_type` is free text, so
 *  there was no migration, and the two totals above are what makes a half-done addition a type
 *  error rather than a raw code in a column. */
describe('winding the clock', () => {
  it('says how far it was asked to go', () => {
    expect(requested(entry({ action: 'world.advance', payload: { days: 30 } }))).toBe('30 days')
    expect(requested(entry({ action: 'world.advance', payload: { days: 1 } }))).toBe('1 day')
  })

  it('says nothing rather than something wrong when the payload is not a distance', () => {
    expect(requested(entry({ action: 'world.advance', payload: {} }))).toBe('')
  })
})
