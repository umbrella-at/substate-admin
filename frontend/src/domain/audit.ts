/**
 * The audit's question, and what one of its rows says.
 *
 * The filters live in the URL for the reason the table's do: a page of the audit narrowed to one
 * subscriber is a thing somebody sends to a colleague, and a screen whose state lives only in
 * component memory is a screen you cannot point at.
 *
 * There is no date range and no sort, and both absences are decisions. An audit log has one order
 * — newest first — and offering another produces something that reads as a ranking of who did the
 * most. A date range needs a date control, which this interface does not have and `docs/design.md`
 * has no recipe for; a filter nobody can operate is not a filter.
 */

import type { AuditAction, AuditEntry } from '@/api/client'
import { money } from '@/domain/events'

export type Outcome = AuditEntry['outcome']

/** The six, in the order the panel offers them: the ones an operator reaches for first. */
export const AUDIT_ACTIONS: readonly AuditAction[] = [
  'subscription.payment',
  'subscription.cancel',
  'subscription.change_plan',
  'subscription.redeem',
  'subscription.subscribe',
  'subscription.assign_program',
] as const

/** What each action was, said as a person would say it.
 *
 *  Total over the six with no fallback, the same construction and the same reason as the state
 *  chip's: a seventh action should arrive as a type error here rather than as a raw code in a
 *  column somebody has to decipher. */
export const ACTION_LABEL: Record<AuditAction, string> = {
  'subscription.subscribe': 'Started a subscription',
  'subscription.cancel': 'Cancelled a subscription',
  'subscription.change_plan': 'Changed the plan',
  'subscription.redeem': 'Redeemed a promo code',
  'subscription.payment': 'Recorded a payment',
  'subscription.assign_program': 'Assigned a referral programme',
}

function text(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key]
  return typeof value === 'string' && value !== '' ? value : null
}

/**
 * What was asked for, in the row's own words.
 *
 * The payload holds the request and nothing derived from it, so this says what the operator
 * submitted and never what came of it — what happened is in the event journal, and repeating it
 * here would make two journals into two versions of one truth.
 */
export function requested(entry: AuditEntry): string {
  const payload = entry.payload
  switch (entry.action) {
    case 'subscription.cancel':
      return ''
    case 'subscription.change_plan':
      return text(payload, 'planId') ?? ''
    case 'subscription.redeem':
      return text(payload, 'promoCode') ?? ''
    case 'subscription.assign_program':
      return text(payload, 'programId') ?? ''
    case 'subscription.subscribe': {
      const plan = text(payload, 'planId') ?? ''
      const code = text(payload, 'promoCode')
      return code === null ? plan : `${plan} with ${code}`
    }
    case 'subscription.payment': {
      const amount = payload['amount']
      const reference = text(payload, 'reference')
      const paid = typeof amount === 'number' ? money(amount) : ''
      return reference === null ? paid : `${paid} · ${reference}`
    }
  }
}

export interface AuditQuery {
  page: number
  actions: AuditAction[]
  outcome: Outcome | null
  targetId: string | null
  actorUserId: string | null
}

export const EMPTY_AUDIT_QUERY: AuditQuery = {
  page: 1,
  actions: [],
  outcome: null,
  targetId: null,
  actorUserId: null,
}

const KNOWN_ACTIONS: ReadonlySet<string> = new Set(AUDIT_ACTIONS)

function isAction(value: string): value is AuditAction {
  return KNOWN_ACTIONS.has(value)
}

function isOutcome(value: string): value is Outcome {
  return value === 'ok' || value === 'refused'
}

type QueryValue = string | null | undefined
type QuerySource = Record<string, QueryValue | readonly QueryValue[]>

function first(value: QueryValue | readonly QueryValue[]): string | null {
  if (Array.isArray(value)) return value.find((entry) => typeof entry === 'string') ?? null
  return typeof value === 'string' ? value : null
}

function all(value: QueryValue | readonly QueryValue[]): string[] {
  if (Array.isArray(value))
    return value.filter((entry): entry is string => typeof entry === 'string')
  return typeof value === 'string' ? [value] : []
}

export function auditQueryFromRoute(source: QuerySource): AuditQuery {
  const page = Number(first(source['page']))
  const outcome = first(source['outcome'])
  const target = first(source['targetId'])
  const actor = first(source['actorUserId'])
  return {
    page: Number.isInteger(page) && page >= 1 ? Math.min(page, 1_000_000) : 1,
    // Deduplicated: two spellings of one question would be two cache entries and two requests.
    actions: [...new Set(all(source['action']).filter(isAction))],
    outcome: outcome !== null && isOutcome(outcome) ? outcome : null,
    targetId: target === null || target.trim() === '' ? null : target.trim(),
    actorUserId: actor === null || actor.trim() === '' ? null : actor.trim(),
  }
}

export function auditQueryToRoute(query: AuditQuery): Record<string, string | string[]> {
  const route: Record<string, string | string[]> = {}
  if (query.page !== 1) route['page'] = String(query.page)
  if (query.actions.length > 0) route['action'] = [...query.actions]
  if (query.outcome !== null) route['outcome'] = query.outcome
  if (query.targetId !== null) route['targetId'] = query.targetId
  if (query.actorUserId !== null) route['actorUserId'] = query.actorUserId
  return route
}

export function auditQueryToSearchParams(query: AuditQuery): URLSearchParams {
  const params = new URLSearchParams()
  params.set('page', String(query.page))
  for (const action of query.actions) params.append('action', action)
  if (query.outcome !== null) params.set('outcome', query.outcome)
  if (query.targetId !== null) params.set('targetId', query.targetId)
  if (query.actorUserId !== null) params.set('actorUserId', query.actorUserId)
  return params
}

export function auditQueryKey(query: AuditQuery): string {
  return auditQueryToSearchParams(query).toString()
}

export function hasAuditFilters(query: AuditQuery): boolean {
  return (
    query.actions.length > 0 ||
    query.outcome !== null ||
    query.targetId !== null ||
    query.actorUserId !== null
  )
}
