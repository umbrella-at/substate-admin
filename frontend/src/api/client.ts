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
export type DemoSession = components['schemas']['DemoSessionResponse']
export type ClockReading = components['schemas']['ClockResponse']
export type SubscriberPage = components['schemas']['SubscriberPage']
export type SubscriberDetail = components['schemas']['SubscriberDetail']
export type SubscriberEventPage = components['schemas']['SubscriberEventPage']
export type SubscriberOperationResult = components['schemas']['SubscriberOperationResult']
export type AuditPage = components['schemas']['AuditPage']
export type AuditEntry = components['schemas']['AuditEntry']
export type AuditAction = AuditEntry['action']
export type PlanSummary = components['schemas']['PlanSummary']
export type ReferralProgramSummary = components['schemas']['ReferralProgramSummary']
export type HealthResponse = components['schemas']['HealthResponse']
export type FunnelResponse = components['schemas']['FunnelResponse']
export type FlowResponse = components['schemas']['FlowResponse']
export type StatesResponse = components['schemas']['StatesResponse']
export type QuietResponse = components['schemas']['QuietResponse']
export type RevenueResponse = components['schemas']['RevenueResponse']
export type UserListResponse = components['schemas']['UserListResponse']
export type UserSummary = components['schemas']['UserSummary']
export type RolesResponse = components['schemas']['RolesResponse']
export type RoleDetail = components['schemas']['RoleDetail']
export type PermissionSummary = components['schemas']['PermissionSummary']
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
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal | undefined
  /** Set on the one retry a request is allowed after a refresh, so a loop is impossible. */
  retried?: boolean
}

const BASE = '/api'

/** Endpoints the renewal machinery must never be applied to: each of them is itself an answer
 *  about a session, so retrying one through a renewal is a loop whose base case is the thing that
 *  just failed. `demo/session` is here because it IS the renewal. */
const NO_REFRESH = new Set([
  `${BASE}/auth/login`,
  `${BASE}/auth/refresh`,
  `${BASE}/auth/logout`,
  `${BASE}/demo/session`,
])

/** Where a demonstration's pass is kept between page loads. An operator's token lives in memory
 *  and nowhere else, because storage outlives the tab and anything injected into the page can read
 *  it — this is the one exception, and a narrow one. */

/* What it buys: a demonstration pass opens invented people, dies within the hour and reaches
   nothing real. Without it F5 ends the demonstration, because there is no refresh cookie to
   rebuild the session from and the wound-forward world becomes unreachable while still standing. */
const DEMO_TOKEN_KEY = 'substate.demo'

function remember(token: string | null): void {
  try {
    if (token === null) globalThis.sessionStorage.removeItem(DEMO_TOKEN_KEY)
    else globalThis.sessionStorage.setItem(DEMO_TOKEN_KEY, token)
  } catch {
    // Private browsing, or storage the visitor has switched off. A demonstration that does not
    // survive a reload is worse than one that does, and better than one that will not open.
  }
}

/** The pass this tab was holding before it was reloaded, if it was holding one. */
export function rememberedDemoToken(): string | null {
  try {
    return globalThis.sessionStorage.getItem(DEMO_TOKEN_KEY)
  } catch {
    return null
  }
}

/** The six paths under a subscriber that change something. A union rather than a string, so a
 *  typo is a build failure instead of a 404 nobody sees until the button is pressed. */
export type OperationPath =
  | 'subscribe'
  | 'cancel'
  | 'change-plan'
  | 'redeem'
  | 'payment'
  | 'referral-program'

export interface ClientHooks {
  /** Called once when the session is definitively over. The app clears its state and navigates. */
  onSessionLost: (reason: ApiError) => void

  /** The visitor's sandbox is gone: the hour ran out, or a deploy restarted the process under
   *  them. A different ending from a session lost, and a different thing to say about it. */
  onDemoEnded: () => void
}

export function createClient(hooks: ClientHooks) {
  /** In memory, never in localStorage: a token in storage outlives the tab, is readable by any
   *  script that gets injected, and cannot be revoked by closing the browser. */
  let accessToken: string | null = null

  /** The single shared refresh. Concurrent 401s await THIS promise rather than each starting their
   *  own exchange — which matters beyond politeness: rotation invalidates the presented token, so
   *  two simultaneous refreshes would be one success and one apparent reuse. */
  let refreshInFlight: Promise<RefreshOutcome> | null = null

  /** Whether the token above is a demonstration pass. It decides which renewal a 401 gets: an
   *  operator's session is rebuilt from the refresh cookie, and a visitor has none. */
  let demo = false

  function setAccessToken(token: string | null): void {
    accessToken = token
    demo = false
    remember(null)
  }

  /** Adopt a demonstration pass, and keep it where a reload can find it again. */
  function setDemoToken(token: string | null): void {
    accessToken = token
    demo = token !== null
    remember(token)
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

  /** A fresh pass for the sandbox this tab is already in. Not a refresh by any of the machinery
   *  that word means here — no cookie, no family, no rotation, nothing to revoke: the server
   *  extends the world, mints a pass for what is left of it, and refuses at the ceiling. */
  async function renewDemo(signal?: AbortSignal): Promise<RefreshOutcome> {
    try {
      const response = await raw(`${BASE}/demo/session`, { method: 'POST', signal })
      if (!response.ok) {
        setDemoToken(null)
        return 'refused'
      }
      const payload = (await parse(response)) as DemoSession | null
      if (payload === null) {
        setDemoToken(null)
        return 'refused'
      }
      setDemoToken(payload.accessToken)
      return 'renewed'
    } catch {
      return 'undeliverable'
    }
  }

  /** Whichever renewal this session has. A demonstration has no refresh cookie to exchange, and
   *  an operator has no sandbox to extend. */
  function renew(signal?: AbortSignal): Promise<RefreshOutcome> {
    return demo ? renewDemo(signal) : refresh(signal)
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

    // A world that has ended is not a session that was lost. The visitor still holds a perfectly
    // good pass; what it named is gone, and telling them to sign in again is advice they cannot
    // take — they never had an account.
    if (error.code === 'SANDBOX_GONE') {
      setDemoToken(null)
      hooks.onDemoEnded()
      throw error
    }

    if (!refreshable) {
      if (error.status === 401 && !NO_REFRESH.has(path)) hooks.onSessionLost(error)
      throw error
    }

    const outcome = await renew(options.signal)
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
    setDemoToken,
    get accessToken() {
      return accessToken
    },
    get isDemo() {
      return demo
    },
    refresh,
    request,

    /** Open a demonstration, or keep the one this tab already holds. The pass in the header, if
     *  there is one, is what makes it the second rather than the first. */
    demoSession: (signal?: AbortSignal) =>
      request<DemoSession>(`${BASE}/demo/session`, { method: 'POST', signal }),

    clock: (signal?: AbortSignal) => request<ClockReading>(`${BASE}/clock`, { signal }),

    // No signal: winding a clock is a write, and cancelling it discards the answer rather than
    // the advance — the world has already moved.
    advanceClock: (days: number) =>
      request<ClockReading>(`${BASE}/clock/advance`, { method: 'POST', body: { days } }),

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

    referralPrograms: (signal?: AbortSignal) =>
      request<ReferralProgramSummary[]>(`${BASE}/referral-programs`, { signal }),

    // Public, and deliberately not behind the session: it is the one endpoint that can be asked
    // whether the demonstration has anything to show before anybody has signed in.
    health: (signal?: AbortSignal) => request<HealthResponse>(`${BASE}/health`, { signal }),

    subscriber: (userId: string, signal: AbortSignal) =>
      request<SubscriberDetail>(`${BASE}/subscribers/${encodeURIComponent(userId)}`, { signal }),

    subscriberEvents: (userId: string, params: URLSearchParams, signal: AbortSignal) =>
      request<SubscriberEventPage>(
        `${BASE}/subscribers/${encodeURIComponent(userId)}/events?${params.toString()}`,
        { signal },
      ),

    audit: (params: URLSearchParams, signal: AbortSignal) =>
      request<AuditPage>(`${BASE}/audit?${params.toString()}`, { signal }),

    // The five figures. Each takes a signal for the reason the table does: the period control
    // changes while a request is out, and the answer to the previous period must not land on top
    // of the answer to this one.
    funnel: (params: URLSearchParams, signal: AbortSignal) =>
      request<FunnelResponse>(`${BASE}/analytics/funnel?${params.toString()}`, { signal }),

    flow: (params: URLSearchParams, signal: AbortSignal) =>
      request<FlowResponse>(`${BASE}/analytics/flow?${params.toString()}`, { signal }),

    states: (signal: AbortSignal) =>
      request<StatesResponse>(`${BASE}/analytics/states`, { signal }),

    quiet: (signal: AbortSignal) => request<QuietResponse>(`${BASE}/analytics/quiet`, { signal }),

    revenue: (params: URLSearchParams, signal: AbortSignal) =>
      request<RevenueResponse>(`${BASE}/analytics/revenue?${params.toString()}`, { signal }),

    users: (params: URLSearchParams, signal: AbortSignal) =>
      request<UserListResponse>(`${BASE}/users?${params.toString()}`, { signal }),

    roles: (signal: AbortSignal) => request<RolesResponse>(`${BASE}/roles`, { signal }),

    // The three writes. No signal, for the reason the subscriber operations give: cancelling a
    // write discards the answer and not the write.
    createRole: (body: { code: string; name: string; permissions: string[] }) =>
      request<RoleDetail>(`${BASE}/roles`, { method: 'POST', body }),

    replaceRole: (roleId: string, body: { name: string; permissions: string[] }) =>
      request<RoleDetail>(`${BASE}/roles/${encodeURIComponent(roleId)}`, { method: 'PUT', body }),

    deleteRole: (roleId: string) =>
      request<null>(`${BASE}/roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' }),

    // The six operations, one signature. They differ by their path and their body and by nothing
    // else, which is what the uniform `{subscriber, events}` answer bought — the alternative was
    // six methods with six response types and six call sites that all had to be right.
    //
    // No AbortSignal, and that is the difference from every read above. Cancelling a read discards
    // an answer; cancelling a write discards the ANSWER, not the write — the engine has already
    // moved and the audit row is already committed. A caller who thinks it undid something would
    // be wrong, so the option is not offered.
    operate: (userId: string, operation: OperationPath, body: unknown) =>
      request<SubscriberOperationResult>(
        `${BASE}/subscribers/${encodeURIComponent(userId)}/${operation}`,
        { method: 'POST', body: body ?? {} },
      ),
  }
}

export type ApiClient = ReturnType<typeof createClient>
