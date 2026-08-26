/**
 * The table's question, and the one place it turns into a query string.
 *
 * Filters, sort and page live in the URL, which makes them a link: a colleague can be sent the
 * eleven people in grace rather than told how to find them, and the back button walks the
 * filters the visitor actually used. That only holds if the URL and the request are built from
 * the same value, so `SubscriberQuery` is that value and both directions are here.
 *
 * Everything is optional and every default is the backend's. A query string that says nothing
 * means the first page, unfiltered, sorted the way the API sorts — so a bare `/subscribers` and
 * a `/subscribers?page=1` are the same request rather than two spellings that could drift.
 */

import type { components, operations } from '@/api/schema'

type Query = NonNullable<operations['list_page_api_subscribers_get']['parameters']['query']>

export type SubscriptionState = components['schemas']['SubscriberSummary']['state']
export type Cohort = NonNullable<Query['cohort']>
export type SubscriberSummary = components['schemas']['SubscriberSummary']
export type SubscriberPage = components['schemas']['SubscriberPage']

/** The five states, in the order a subscription passes through them rather than alphabetically:
 *  the filter reads as a lifecycle, and `expired` sits next to the states it came from. */
export const STATES: readonly SubscriptionState[] = [
  'trial',
  'active',
  'grace',
  'expired',
  'cancelled',
] as const

/** The cohorts, with the question each one answers.
 *
 *  Named for the person, not the predicate. "Quiet" is a column of people who have not been seen
 *  in a month; calling it `last_active_at < now() - 30d` in the interface would move the reader's
 *  work from reading to translating. */
export const COHORTS: readonly { value: Cohort; label: string }[] = [
  { value: 'in-grace', label: 'In grace' },
  { value: 'trial-ending', label: 'Trial ending' },
  { value: 'quiet', label: 'Quiet' },
  { value: 'cancelled-still-active', label: 'Cancelled, still active' },
] as const

/** The columns the backend will sort by. Kept as a list here so an unknown `sort=` in a
 *  hand-edited URL is dropped on the way in rather than sent on to be refused. */
export const SORT_FIELDS = [
  'displayName',
  'state',
  'planId',
  'expiresAt',
  'lastActiveAt',
] as const
export type SortField = (typeof SORT_FIELDS)[number]

export interface Sort {
  field: SortField
  descending: boolean
}

export interface SubscriberQuery {
  page: number
  pageSize: number
  sort: Sort | null
  states: SubscriptionState[]
  planId: string | null
  cohort: Cohort | null
  q: string | null
}

export const DEFAULT_PAGE_SIZE = 25

/** The bounds the API enforces. Mirrored rather than discovered by being refused: a hand-edited
 *  `?pageSize=400` should give the table it asks for as closely as the API allows, not an error
 *  page about a query parameter. The values are the ones in the request schema, and a test asks
 *  the running service to confirm them. */
export const MAX_PAGE_SIZE = 100
export const MAX_PAGE = 1_000_000

export const EMPTY_QUERY: SubscriberQuery = {
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
  sort: null,
  states: [],
  planId: null,
  cohort: null,
  q: null,
}

function isState(value: string): value is SubscriptionState {
  return (STATES as readonly string[]).includes(value)
}

function isCohort(value: string): value is Cohort {
  return COHORTS.some((cohort) => cohort.value === value)
}

function isSortField(value: string): value is SortField {
  return (SORT_FIELDS as readonly string[]).includes(value)
}

/** `-expiresAt` means descending, matching what the API accepts, so the URL and the request say
 *  the same word and nothing has to be translated in between. */
export function parseSort(raw: string | null): Sort | null {
  if (raw === null || raw === '') return null
  const descending = raw.startsWith('-')
  const field = descending ? raw.slice(1) : raw
  return isSortField(field) ? { field, descending } : null
}

export function formatSort(sort: Sort | null): string | null {
  if (sort === null) return null
  return sort.descending ? `-${sort.field}` : sort.field
}

/** A whole number inside the bounds, or the fallback. Anything else in the URL — a word, a
 *  negative, a fraction — is somebody editing the address bar, and the readable answer is the
 *  nearest table that exists rather than an error page about a query parameter. */
function bounded(raw: string | null, fallback: number, limit: number): number {
  if (raw === null) return fallback
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1) return fallback
  return Math.min(value, limit)
}

/** Deliberately the shape vue-router hands over rather than a tidier one. `?state` with no value
 *  is a `null` inside the array, and a type that promised `string[]` would have been a cast that
 *  moved the problem to whoever indexed it. */
type QueryValue = string | null | undefined
type QuerySource = Record<string, QueryValue | readonly QueryValue[]>

function first(value: QueryValue | readonly QueryValue[]): string | null {
  if (Array.isArray(value)) return value.find((entry) => typeof entry === 'string') ?? null
  return typeof value === 'string' ? value : null
}

function all(value: QueryValue | readonly QueryValue[]): string[] {
  if (Array.isArray(value)) return value.filter((entry): entry is string => typeof entry === 'string')
  return typeof value === 'string' ? [value] : []
}

export function queryFromRoute(source: QuerySource): SubscriberQuery {
  const q = first(source['q'])
  const planId = first(source['planId'])
  const cohort = first(source['cohort'])
  return {
    page: bounded(first(source['page']), 1, MAX_PAGE),
    pageSize: bounded(first(source['pageSize']), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE),
    sort: parseSort(first(source['sort'])),
    // Deduplicated: `?state=active&state=active` is one filter, and letting it through would
    // send the same value twice and make two identical URLs cache as different questions.
    states: [...new Set(all(source['state']).filter(isState))],
    planId: planId === null || planId === '' ? null : planId,
    cohort: cohort !== null && isCohort(cohort) ? cohort : null,
    q: q === null || q.trim() === '' ? null : q.trim(),
  }
}

/** What goes in the address bar. Defaults are omitted so the common URL stays short and two
 *  routes that mean the same thing are spelled the same way. */
export function queryToRoute(query: SubscriberQuery): Record<string, string | string[]> {
  const route: Record<string, string | string[]> = {}
  if (query.page !== 1) route['page'] = String(query.page)
  if (query.pageSize !== DEFAULT_PAGE_SIZE) route['pageSize'] = String(query.pageSize)
  const sort = formatSort(query.sort)
  if (sort !== null) route['sort'] = sort
  if (query.states.length > 0) route['state'] = [...query.states]
  if (query.planId !== null) route['planId'] = query.planId
  if (query.cohort !== null) route['cohort'] = query.cohort
  if (query.q !== null) route['q'] = query.q
  return route
}

/** What goes to the API. Page and size are always sent: the backend's defaults and ours agreeing
 *  today is not a reason for the request to depend on their agreeing tomorrow. */
export function queryToSearchParams(query: SubscriberQuery): URLSearchParams {
  const params = new URLSearchParams()
  params.set('page', String(query.page))
  params.set('pageSize', String(query.pageSize))
  const sort = formatSort(query.sort)
  if (sort !== null) params.set('sort', sort)
  for (const state of query.states) params.append('state', state)
  if (query.planId !== null) params.set('planId', query.planId)
  if (query.cohort !== null) params.set('cohort', query.cohort)
  if (query.q !== null) params.set('q', query.q)
  return params
}

/** The identity of a question, for the cache and for deciding whether a request in flight is
 *  still the one being waited on. Built from the same value as the URL and the request, so all
 *  three agree by construction. */
export function queryKey(query: SubscriberQuery): string {
  return queryToSearchParams(query).toString()
}
