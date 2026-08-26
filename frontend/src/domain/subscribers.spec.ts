import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PAGE_SIZE,
  DEFAULT_SORT,
  EMPTY_QUERY,
  MAX_PAGE_SIZE,
  parseSort,
  queryFromRoute,
  queryKey,
  queryToRoute,
  queryToSearchParams,
} from './subscribers'

describe('reading the question out of the URL', () => {
  it('reads an empty address as the first page, unfiltered', () => {
    expect(queryFromRoute({})).toEqual(EMPTY_QUERY)
  })

  it('keeps every filter the address carries', () => {
    const query = queryFromRoute({
      page: '3',
      sort: '-expiresAt',
      state: ['grace', 'trial'],
      cohort: 'quiet',
      planId: 'monthly',
      q: 'ada',
    })
    expect(query.page).toBe(3)
    expect(query.sort).toEqual({ field: 'expiresAt', descending: true })
    expect(query.states).toEqual(['grace', 'trial'])
    expect(query.cohort).toBe('quiet')
    expect(query.planIds).toEqual(['monthly'])
    expect(query.q).toBe('ada')
  })

  // A hand-edited address is the normal way these arrive, and the readable answer is the
  // unfiltered table rather than an error page about a query parameter.
  it('drops values the API would refuse instead of forwarding them', () => {
    const query = queryFromRoute({
      page: 'first',
      pageSize: '-4',
      sort: 'passwordHash',
      state: ['grace', 'nonsense'],
      cohort: 'invented',
    })
    expect(query.page).toBe(1)
    expect(query.pageSize).toBe(DEFAULT_PAGE_SIZE)
    // Falls back to the order the API would have applied anyway, rather than to no order.
    expect(query.sort).toEqual(DEFAULT_SORT)
    expect(query.states).toEqual(['grace'])
    expect(query.cohort).toBeNull()
  })

  // The API refuses anything larger, and being refused is not a readable answer for somebody who
  // edited the address.
  it('clamps a page size the API would refuse', () => {
    expect(queryFromRoute({ pageSize: '400' }).pageSize).toBe(MAX_PAGE_SIZE)
  })

  it('treats a repeated state as one filter', () => {
    expect(queryFromRoute({ state: ['grace', 'grace'] }).states).toEqual(['grace'])
  })

  // `?state` with no value arrives as a null inside the array, and it must not become a filter.
  it('ignores a parameter with no value', () => {
    expect(queryFromRoute({ state: [null, 'grace'], q: null }).states).toEqual(['grace'])
  })

  it('treats blank search text as no search', () => {
    expect(queryFromRoute({ q: '   ' }).q).toBeNull()
  })
})

describe('writing the question back', () => {
  it('leaves defaults out of the address', () => {
    expect(queryToRoute(EMPTY_QUERY)).toEqual({})
  })

  // The property that makes the URL a link rather than a decoration: what the address says and
  // what the table asked for are the same value, in both directions.
  it('survives a round trip through the address bar', () => {
    const query = {
      ...EMPTY_QUERY,
      page: 4,
      pageSize: 50,
      sort: { field: 'lastActiveAt' as const, descending: false },
      states: ['active' as const, 'grace' as const],
      cohort: 'quiet' as const,
      planIds: ['annual'],
      q: 'ada',
    }
    expect(queryFromRoute(queryToRoute(query))).toEqual(query)
  })

  it('always sends page and size, so the API default and ours cannot drift apart', () => {
    const params = queryToSearchParams(EMPTY_QUERY)
    expect(params.get('page')).toBe('1')
    expect(params.get('pageSize')).toBe(String(DEFAULT_PAGE_SIZE))
  })

  it('sends each state as its own parameter', () => {
    const params = queryToSearchParams({ ...EMPTY_QUERY, states: ['trial', 'grace'] })
    expect(params.getAll('state')).toEqual(['trial', 'grace'])
  })

  // Two spellings of one question must be one cache entry, or the same table would be fetched
  // twice and the second answer would replace an identical first for no reason.
  it('gives one key to one question', () => {
    const a = queryFromRoute({ q: 'ada', state: ['grace'] })
    const b = queryFromRoute({ state: ['grace'], q: 'ada' })
    expect(queryKey(a)).toBe(queryKey(b))
  })

  it('gives different keys to different pages', () => {
    expect(queryKey({ ...EMPTY_QUERY, page: 2 })).not.toBe(queryKey(EMPTY_QUERY))
  })
})

describe('sort', () => {
  it('reads a leading minus as descending', () => {
    expect(parseSort('-state')).toEqual({ field: 'state', descending: true })
    expect(parseSort('state')).toEqual({ field: 'state', descending: false })
  })

  it('refuses a column the API does not sort by', () => {
    expect(parseSort('secret')).toBeNull()
  })

  // Sending it is what keeps the header honest if the API's default ever moves.
  it('is always sent to the API, even when the address does not carry it', () => {
    expect(queryToSearchParams(EMPTY_QUERY).get('sort')).toBe('-lastActiveAt')
  })

  it('stays out of the address while it is the default', () => {
    expect(queryToRoute(EMPTY_QUERY)).not.toHaveProperty('sort')
    expect(queryToRoute({ ...EMPTY_QUERY, sort: DEFAULT_SORT })).toEqual({})
  })
})
