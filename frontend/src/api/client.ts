/**
 * The HTTP client. Transport only: it knows about tokens, refreshing and error shape, and nothing
 * about Vue, Pinia or the router. What it cannot decide on its own — where to send someone whose
 * session ended — it hands back through `onSessionLost`.
 *
 * Written over native fetch rather than a library because the two things that actually matter here
 * are the refresh promise and the retry rule, and neither is something a library would do for us.
 */

import type { components } from './schema'

type ErrorBody = components['schemas']['ErrorBody']
export type ErrorCode = components['schemas']['ErrorCode']
export type TokenResponse = components['schemas']['TokenResponse']
export type MeResponse = components['schemas']['MeResponse']
export type SubscriberPage = components['schemas']['SubscriberPage']
export type SubscriberDetail = components['schemas']['SubscriberDetail']
export type PlanSummary = components['schemas']['PlanSummary']
export type HealthResponse = components['schemas']['HealthResponse']
/** The three things asking for a new access token can mean, and they must stay three. Collapsing
 *  the last two into one boolean is what turns a two-second deploy restart into every open tab
 *  being signed out of a session the server still considers perfectly valid. */
export type RefreshOutcome = 'renewed' | 'refused' | 'undeliverable'

/** A failure the API described. Anything else — a dropped connection, a timeout — stays a
 *  TypeError or an AbortError, because those mean something different and must not be mistaken
 *  for the server having an opinion. */
export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorCode | 'UNKNOWN'
  readonly field: string | null

  constructor(status: number, body: ErrorBody | null) {
    super(body?.message ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = body?.code ?? 'UNKNOWN'
    this.field = body?.field ?? null
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal | undefined
  /** Set on the one retry a request is allowed after a refresh, so a loop is impossible. */
  retried?: boolean
}

const BASE = '/api'

/** Endpoints the refresh machinery must never be applied to. `login` answers 401 when the password
 *  is wrong, and `refresh` answers 401 when the session is over; retrying either through a refresh
 *  would be a loop whose base case is the thing that just failed. */
const NO_REFRESH = new Set([`${BASE}/auth/login`, `${BASE}/auth/refresh`, `${BASE}/auth/logout`])

export interface ClientHooks {
  /** Called once when the session is definitively over. The app clears its state and navigates. */
  onSessionLost: (reason: ApiError) => void
}

export function createClient(hooks: ClientHooks) {
  /** In memory, never in localStorage: a token in storage outlives the tab, is readable by any
   *  script that gets injected, and cannot be revoked by closing the browser. */
  let accessToken: string | null = null

  /** The single shared refresh. Concurrent 401s await THIS promise rather than each starting their
   *  own exchange — which matters beyond politeness: rotation invalidates the presented token, so
   *  two simultaneous refreshes would be one success and one apparent reuse. */
  let refreshInFlight: Promise<RefreshOutcome> | null = null

  function setAccessToken(token: string | null): void {
    accessToken = token
  }

  async function parse(response: Response): Promise<unknown> {
    if (response.status === 204) return null
    const text = await response.text()
    if (text === '') return null
    try {
      return JSON.parse(text) as unknown
    } catch {
      return null
    }
  }

  function envelope(payload: unknown): ErrorBody | null {
    if (typeof payload !== 'object' || payload === null) return null
    const error = (payload as { error?: unknown }).error
    if (typeof error !== 'object' || error === null) return null
    return error as ErrorBody
  }

  async function raw(path: string, options: RequestOptions): Promise<Response> {
    const headers: Record<string, string> = { accept: 'application/json' }
    if (options.body !== undefined) headers['content-type'] = 'application/json'
    if (accessToken !== null) headers['authorization'] = `Bearer ${accessToken}`

    return fetch(path, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? null : JSON.stringify(options.body),
      // Same origin in development and in production alike, so the refresh cookie behaves
      // identically in both. Stated rather than defaulted: this is the line that would have to
      // change if the API ever moved to another host, and it should be found when it does.
      credentials: 'same-origin',
      signal: options.signal ?? null,
    })
  }

  /** Exchange the refresh cookie for a new access token. Never throws: the caller decides what
   *  each outcome means for it. */
  async function refresh(signal?: AbortSignal): Promise<RefreshOutcome> {
    if (refreshInFlight !== null) return refreshInFlight

    refreshInFlight = (async (): Promise<RefreshOutcome> => {
      try {
        const response = await raw(`${BASE}/auth/refresh`, { method: 'POST', signal })
        if (!response.ok) {
          // The server looked at the cookie and said no. That is the end of the session.
          accessToken = null
          return 'refused'
        }
        const payload = (await parse(response)) as TokenResponse | null
        if (payload === null) {
          accessToken = null
          return 'refused'
        }
        accessToken = payload.accessToken
        return 'renewed'
      } catch {
        // The question never reached the server, so nothing was answered. Leave the token where
        // it is: a dropped connection is not a verdict about the session.
        return 'undeliverable'
      } finally {
        refreshInFlight = null
      }
    })()

    return refreshInFlight
  }

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await raw(path, options)
    if (response.ok) return (await parse(response)) as T

    const body = envelope(await parse(response))
    const error = new ApiError(response.status, body)

    // Only an EXPIRED token is worth refreshing. A missing or malformed one will not become valid,
    // and a 403 is an answer about permissions that no amount of refreshing changes — retrying
    // either would hide the real cause behind a redirect to the login page.
    const refreshable =
      error.status === 401 &&
      error.code === 'TOKEN_EXPIRED' &&
      options.retried !== true &&
      !NO_REFRESH.has(path)

    if (!refreshable) {
      if (error.status === 401 && !NO_REFRESH.has(path)) hooks.onSessionLost(error)
      throw error
    }

    const outcome = await refresh(options.signal)
    if (outcome === 'refused') {
      hooks.onSessionLost(error)
      throw error
    }
    if (outcome === 'undeliverable') {
      // Nothing was decided about the session, so nothing is torn down. The original 401 is
      // surfaced and whoever asked can try again when the network comes back.
      throw error
    }
    return request<T>(path, { ...options, retried: true })
  }

  return {
    setAccessToken,
    get accessToken() {
      return accessToken
    },
    refresh,
    request,

    login: (email: string, password: string, signal?: AbortSignal) =>
      request<TokenResponse>(`${BASE}/auth/login`, {
        method: 'POST',
        body: { email, password },
        signal,
      }),

    logout: () => request<null>(`${BASE}/auth/logout`, { method: 'POST' }),

    me: (signal?: AbortSignal) => request<MeResponse>(`${BASE}/auth/me`, { signal }),

    // The signal is required rather than optional. Every caller of this is a table whose filters
    // change while a request is in flight, and a page of the previous question arriving after the
    // page of the current one is the defect this parameter exists to prevent.
    subscribers: (params: URLSearchParams, signal: AbortSignal) =>
      request<SubscriberPage>(`${BASE}/subscribers?${params.toString()}`, { signal }),

    plans: (signal?: AbortSignal) => request<PlanSummary[]>(`${BASE}/plans`, { signal }),

    // Public, and deliberately not behind the session: it is the one endpoint that can be asked
    // whether the demonstration has anything to show before anybody has signed in.
    health: (signal?: AbortSignal) => request<HealthResponse>(`${BASE}/health`, { signal }),

    subscriber: (userId: string, signal: AbortSignal) =>
      request<SubscriberDetail>(`${BASE}/subscribers/${encodeURIComponent(userId)}`, { signal }),
  }
}

export type ApiClient = ReturnType<typeof createClient>
