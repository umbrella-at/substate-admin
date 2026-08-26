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
 *  work from reading to translating.
 *
 *  Every one of them asks something the state checkboxes cannot. There was a fourth, "In grace",
 *  whose predicate on the API side was literally `state is GRACE` — the same question as the
 *  checkbox two controls to its left, in a second vocabulary. Two controls doing one thing, side
 *  by side, make everybody who sees them work out whether the difference means something. */
export const COHORTS: readonly { value: Cohort; label: string }[] = [
  { value: 'trial-ending', label: 'Trial ending' },
  { value: 'quiet', label: 'Quiet' },
  { value: 'cancelled-still-active', label: 'Cancelled, still active' },
] as const

/** The columns the backend will sort by. Kept as a list here so an unknown `sort=` in a
 *  hand-edited URL is dropped on the way in rather than sent on to be refused.
 *
 *  `planId` is absent because a plan is a category: any order over the five would be invented,
 *  and the alphabetical one would be about the letters of their names. `state` is here because
 *  states do have an order — see `URGENCY_SORT`. */
export const SORT_FIELDS = ['displayName', 'state', 'accessUntil', 'lastActiveAt'] as const
export type SortField = (typeof SORT_FIELDS)[number]

export interface Sort {
  field: SortField
  descending: boolean
}

export interface SubscriberQuery {
  page: number
  pageSize: number
  sort: Sort
  states: SubscriptionState[]
  planIds: string[]
  cohort: Cohort | null
  q: string | null
}

export const DEFAULT_PAGE_SIZE = 25

/** The order the API applies when asked for none.
 *
 *  Stated here rather than left implicit, because a table cannot show an order it does not know
 *  it has: with no sort in the address the header drew no arrow while the rows arrived newest
 *  first, so the column order was real and the only thing that could explain it said nothing.
 *  Mirroring the API's default is what makes the header honest on the first screen; a test asks
 *  the running service to confirm the two still agree. */
export const DEFAULT_SORT: Sort = { field: 'lastActiveAt', descending: true }

/** Sorting by state, which the API orders by urgency rather than alphabetically: in grace first,
 *  then trials, then everyone there is nothing to do about.
 *
 *  It is offered as one named thing rather than as an arrow on the State header. An arrow is a
 *  direction over a quantity, and a state is not one — the glyph would promise that the column
 *  runs from small to large and say nothing about what the order actually is. So the control
 *  carries the name of the order, and reversing it is not offered: the reverse of "most urgent
 *  first" is a list nobody opens this table to see. */
export const URGENCY_SORT: Sort = { field: 'state', descending: false }

/** The bounds the API enforces. Mirrored rather than discovered by being refused: a hand-edited
 *  `?pageSize=400` should give the table it asks for as closely as the API allows, not an error
 *  page about a query parameter. The values are the ones in the request schema, and a test asks
 *  the running service to confirm them. */
export const MAX_PAGE_SIZE = 100
export const MAX_PAGE = 1_000_000

export const EMPTY_QUERY: SubscriberQuery = {
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
  sort: DEFAULT_SORT,
  states: [],
  planIds: [],
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

export function formatSort(sort: Sort): string {
  return sort.descending ? `-${sort.field}` : sort.field
}

function sameSort(a: Sort, b: Sort): boolean {
  return a.field === b.field && a.descending === b.descending
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
  const cohort = first(source['cohort'])
  return {
    page: bounded(first(source['page']), 1, MAX_PAGE),
    pageSize: bounded(first(source['pageSize']), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE),
    sort: parseSort(first(source['sort'])) ?? DEFAULT_SORT,
    // Deduplicated: `?state=active&state=active` is one filter, and letting it through would
    // send the same value twice and make two identical URLs cache as different questions.
    states: [...new Set(all(source['state']).filter(isState))],
    // Deduplicated like the states, and for the same reason: two spellings of one question would
    // be two cache entries and two requests for one answer.
    planIds: [...new Set(all(source['planId']).filter((plan) => plan !== ''))],
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
  if (!sameSort(query.sort, DEFAULT_SORT)) route['sort'] = formatSort(query.sort)
  if (query.states.length > 0) route['state'] = [...query.states]
  if (query.planIds.length > 0) route['planId'] = [...query.planIds]
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
  // Always sent, like page and size: the API's default and ours agreeing today is not a reason
  // for the request to depend on their agreeing tomorrow.
  params.set('sort', formatSort(query.sort))
  for (const state of query.states) params.append('state', state)
  for (const planId of query.planIds) params.append('planId', planId)
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
