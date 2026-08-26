/**
 * The two hard parts of the client, and the rules that keep them from eating a session.
 *
 * Everything asserted here is a decision that is invisible in the types and expensive to get
 * wrong. A second refresh running beside the first is not a slower login — rotation invalidates
 * the token the first one presented, so the second exchange arrives looking like a reused refresh
 * token, which is the one event the backend answers by revoking the whole family. A retry that
 * does not stop is an infinite loop against `/auth/refresh` from a page that looks frozen. And a
 * 401 from `/auth/login` that is treated as an expired session ends with a wrong password logging
 * somebody out of a session they never had.
 *
 * The fetch here is a stub on purpose: these are statements about the client's own control flow,
 * and a real server would only add a second thing that can be wrong.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, createClient, type ErrorCode } from '@/api/client'

const REFRESH = '/api/auth/refresh'
const LOGIN = '/api/auth/login'
const LOGOUT = '/api/auth/logout'

/** Exactly the fields of a fetch init this client sets. Written out rather than reused from
 *  `RequestInit` so that a test can read a header without a cast, and so the day the client
 *  starts sending something else, this interface is where it is noticed. */
interface Sent {
  method: string
  headers: Record<string, string>
  body: string | null
  credentials: string
  signal: AbortSignal | null
}

const fetchMock = vi.fn<(path: string, init: Sent) => Promise<Response>>()
const onSessionLost = vi.fn()

function client() {
  return createClient({ onSessionLost })
}

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

/** A refusal in the envelope the API actually sends: `{ error: { code, message } }`. */
function refused(status: number, code: ErrorCode, message = 'refused'): Response {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function paths(): string[] {
  return fetchMock.mock.calls.map(([path]) => path)
}

function callsTo(path: string): Sent[] {
  return fetchMock.mock.calls.filter(([sent]) => sent === path).map(([, init]) => init)
}

beforeEach(() => {
  fetchMock.mockReset()
  onSessionLost.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the shared refresh', () => {
  it('exchanges once for any number of requests that expired together, and retries them all', async () => {
    // The realistic shape of a tab left open over lunch: the dashboard fires several requests at
    // once, every one of them carrying the same access token, and every one comes back expired.
    let refreshed = false
    fetchMock.mockImplementation(async (path) => {
      if (path === REFRESH) {
        refreshed = true
        return ok({ accessToken: 'fresh', expiresIn: 900 })
      }
      return refreshed ? ok({ path }) : refused(401, 'TOKEN_EXPIRED')
    })

    const api = client()
    api.setAccessToken('stale')

    const wanted = ['/api/a', '/api/b', '/api/c', '/api/d', '/api/e']
    const answers = await Promise.all(wanted.map((path) => api.request<{ path: string }>(path)))

    // Every one of them resolved with its own answer — a shared refresh must not turn into a
    // shared response.
    expect(answers.map((answer) => answer.path)).toEqual(wanted)

    expect(callsTo(REFRESH)).toHaveLength(1)
    for (const path of wanted) expect(callsTo(path)).toHaveLength(2)

    // The order says the sharing is real rather than accidental: all five expired before any
    // exchange started, and nothing was retried until the single exchange had answered.
    expect(paths().slice(0, 5)).toEqual(wanted)
    expect(paths()[5]).toBe(REFRESH)

    // The retry carried the NEW token. Retrying with the stale one would 401 again and burn the
    // one retry each request is allowed.
    const attempts = callsTo('/api/a')
    expect(attempts[0]?.headers['authorization']).toBe('Bearer stale')
    expect(attempts[1]?.headers['authorization']).toBe('Bearer fresh')
    expect(api.accessToken).toBe('fresh')

    expect(onSessionLost).not.toHaveBeenCalled()
  })

  it('gives up after one retry rather than looping', async () => {
    // The pathological case: the refresh keeps succeeding and the request keeps being refused.
    // Without the retry flag this is an infinite exchange against the API from a page that simply
    // looks frozen, so the mock fails loudly rather than letting the test hang.
    let attempts = 0
    fetchMock.mockImplementation(async (path) => {
      if (path === REFRESH) return ok({ accessToken: 'fresh', expiresIn: 900 })
      attempts += 1
      if (attempts > 4) throw new Error('the client looped: it refreshed and retried without end')
      return refused(401, 'TOKEN_EXPIRED')
    })

    const api = client()
    api.setAccessToken('stale')

    await expect(api.request('/api/a')).rejects.toBeInstanceOf(ApiError)

    expect(callsTo('/api/a')).toHaveLength(2)
    expect(callsTo(REFRESH)).toHaveLength(1)
    // Refreshing worked and the request was still refused: that is a session that is over, and
    // the app has to be told once so it can navigate.
    expect(onSessionLost).toHaveBeenCalledTimes(1)
  })

  it('reports a session as lost when the refresh itself is refused', async () => {
    fetchMock.mockImplementation(async (path) => {
      if (path === REFRESH) return refused(401, 'REFRESH_TOKEN_INVALID')
      return refused(401, 'TOKEN_EXPIRED')
    })

    const api = client()
    api.setAccessToken('stale')

    const failure = await api.request('/api/a').catch((cause: unknown) => cause)
    expect(failure).toBeInstanceOf(ApiError)
    // The original error, not the refresh's. What the caller asked for is what failed; the
    // refresh is machinery they never asked to run.
    expect((failure as ApiError).code).toBe('TOKEN_EXPIRED')
    expect(onSessionLost).toHaveBeenCalledTimes(1)
    expect(api.accessToken).toBeNull()
  })
})

describe('what is worth refreshing', () => {
  it('does not refresh a 401 that says the token was never valid', async () => {
    fetchMock.mockImplementation(async () => refused(401, 'NOT_AUTHENTICATED'))

    const api = client()
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).code).toBe('NOT_AUTHENTICATED')
    // A missing or malformed token does not become valid by being exchanged, and trying would
    // hide the real cause behind a redirect to the login page.
    expect(callsTo(REFRESH)).toHaveLength(0)
    expect(onSessionLost).toHaveBeenCalledTimes(1)
  })

  it('does not refresh a 403, and does not treat it as the end of the session', async () => {
    fetchMock.mockImplementation(async () => refused(403, 'PERMISSION_DENIED'))

    const api = client()
    api.setAccessToken('good')
    const failure = await api.request('/api/users').catch((cause: unknown) => cause)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).status).toBe(403)
    expect(callsTo(REFRESH)).toHaveLength(0)
    // "You may not" is an answer about permissions. Signing the person out over it would be the
    // interface deciding they are not who they are.
    expect(onSessionLost).not.toHaveBeenCalled()
    expect(api.accessToken).toBe('good')
  })
})

describe('the endpoints the machinery must not touch', () => {
  it('reads a 401 from login as a wrong password, not as a session that ended', async () => {
    fetchMock.mockImplementation(async () => refused(401, 'INVALID_CREDENTIALS'))

    const api = client()
    const failure = await api.login('operator@example.com', 'wrong').catch((c: unknown) => c)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).code).toBe('INVALID_CREDENTIALS')
    expect(paths()).toEqual([LOGIN])
    // Nothing to lose and nowhere to send anyone: they are already on the login page.
    expect(onSessionLost).not.toHaveBeenCalled()
  })

  it('does not refresh the refresh, whose failure is the base case', async () => {
    fetchMock.mockImplementation(async () => refused(401, 'REFRESH_TOKEN_INVALID'))

    const api = client()
    api.setAccessToken('stale')

    await expect(api.refresh()).resolves.toBe('refused')
    expect(paths()).toEqual([REFRESH])
    expect(api.accessToken).toBeNull()
  })

  it('does not refresh a logout, which is a session ending on purpose', async () => {
    fetchMock.mockImplementation(async () => refused(401, 'TOKEN_EXPIRED'))

    const api = client()
    await expect(api.logout()).rejects.toBeInstanceOf(ApiError)
    expect(paths()).toEqual([LOGOUT])
    // Signing out of a session that had already expired is a success in every way the person
    // cares about; it must not arrive back as "your session ended" over the login page.
    expect(onSessionLost).not.toHaveBeenCalled()
  })
})

describe('failures that are not the server refusing', () => {
  it('leaves the session alone when the API is broken rather than unconvinced', async () => {
    fetchMock.mockImplementation(async () =>
      refused(500, 'INTERNAL_ERROR', 'Something went wrong.'),
    )

    const api = client()
    api.setAccessToken('good')
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).status).toBe(500)
    expect(callsTo(REFRESH)).toHaveLength(0)
    expect(onSessionLost).not.toHaveBeenCalled()
    expect(api.accessToken).toBe('good')
  })

  it('does not turn a dropped connection into an ApiError', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')))

    const api = client()
    api.setAccessToken('good')
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    // The distinction the whole error handling rests on: an ApiError means the server looked at
    // the request and said no. Nothing here was ever looked at.
    expect(failure).not.toBeInstanceOf(ApiError)
    expect(failure).toBeInstanceOf(TypeError)
    expect(onSessionLost).not.toHaveBeenCalled()
    expect(api.accessToken).toBe('good')
  })

  it('keeps the token when the refresh cannot be delivered at all', async () => {
    // A two-second systemd restart during a deploy. Nulling the token here would sign every open
    // tab out of a session the server still considers perfectly valid.
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')))

    const api = client()
    api.setAccessToken('good')

    await expect(api.refresh()).resolves.toBe('undeliverable')
    expect(api.accessToken).toBe('good')
  })

  it('does not end the session when the refresh behind a 401 never reaches the server', async () => {
    // The whole reason `refresh()` reports three outcomes rather than two. A request 401s with an
    // expired token, the follow-up refresh lands in the middle of a deploy restart, and nothing
    // was decided about the session — so nothing may be torn down. Reported as a boolean, this
    // case is indistinguishable from the server refusing the cookie, and every open tab gets
    // signed out of a session that is still perfectly valid.
    fetchMock.mockImplementation(async (path: string) => {
      if (path === REFRESH) throw new TypeError('Failed to fetch')
      return refused(401, 'TOKEN_EXPIRED')
    })

    const api = client()
    api.setAccessToken('expired')

    await expect(api.request('/api/users')).rejects.toBeInstanceOf(ApiError)
    expect(onSessionLost).not.toHaveBeenCalled()
    expect(api.accessToken).toBe('expired')
    expect(paths()).toEqual(['/api/users', REFRESH])
  })

  it('does not turn an abort into an ApiError either', async () => {
    fetchMock.mockImplementation(() =>
      Promise.reject(new DOMException('The operation was aborted.', 'AbortError')),
    )

    const api = client()
    api.setAccessToken('good')
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    expect(failure).not.toBeInstanceOf(ApiError)
    expect((failure as DOMException).name).toBe('AbortError')
    expect(onSessionLost).not.toHaveBeenCalled()
    expect(api.accessToken).toBe('good')
  })
})

describe('cancellation', () => {
  it('hands the signal to fetch and rejects when it fires', async () => {
    fetchMock.mockImplementation(
      (_path, init) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'))
          })
        }),
    )

    const api = client()
    const controller = new AbortController()
    const pending = api.request('/api/slow', { signal: controller.signal })
    // Attached before anything is awaited, so an unhandled rejection cannot be reported between
    // the abort and the assertion.
    const settled = pending.catch((cause: unknown) => cause)

    expect(callsTo('/api/slow')[0]?.signal).toBe(controller.signal)

    controller.abort()
    const failure = await settled

    expect((failure as DOMException).name).toBe('AbortError')
    expect(onSessionLost).not.toHaveBeenCalled()
  })

  it('passes a signal through the typed helpers as well', async () => {
    fetchMock.mockImplementation(async () => ok({ kind: 'user' }))

    const api = client()
    const controller = new AbortController()
    await api.me(controller.signal)

    expect(callsTo('/api/auth/me')[0]?.signal).toBe(controller.signal)
  })
})

describe('the request it actually sends', () => {
  it('sends JSON with a content type, and omits both when there is no body', async () => {
    fetchMock.mockImplementation(async () => ok({ accessToken: 'a', expiresIn: 900 }))

    const api = client()
    await api.login('operator@example.com', 'correct horse battery staple')

    const sent = callsTo(LOGIN)[0]
    expect(sent?.method).toBe('POST')
    expect(sent?.headers['content-type']).toBe('application/json')
    expect(sent?.body).toBe(
      JSON.stringify({ email: 'operator@example.com', password: 'correct horse battery staple' }),
    )
    // Same origin in development and in production alike, so the refresh cookie behaves
    // identically in both.
    expect(sent?.credentials).toBe('same-origin')

    await api.request('/api/a')
    const plain = callsTo('/api/a')[0]
    expect(plain?.method).toBe('GET')
    expect(plain?.headers['content-type']).toBeUndefined()
    expect(plain?.body).toBeNull()
  })

  it('sends no authorization header at all when there is no token', async () => {
    fetchMock.mockImplementation(async () => ok({}))

    const api = client()
    await api.request('/api/a')

    // Not an empty `Bearer `, which some servers parse as a malformed token and answer 400.
    expect(callsTo('/api/a')[0]?.headers).not.toHaveProperty('authorization')
  })

  it('reads an empty 204 as null rather than choking on it', async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }))

    const api = client()
    await expect(api.request('/api/a')).resolves.toBeNull()
  })

  it('survives a refusal whose body is not JSON at all', async () => {
    // What a proxy returns when the API is down: an HTML error page with a 502. The client still
    // has to produce an ApiError rather than a parse exception.
    fetchMock.mockImplementation(
      async () => new Response('<html>502 Bad Gateway</html>', { status: 502 }),
    )

    const api = client()
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).status).toBe(502)
    expect((failure as ApiError).code).toBe('UNKNOWN')
    expect((failure as ApiError).field).toBeNull()
  })

  it('carries the field of a validation error, so a form can point at the input', async () => {
    fetchMock.mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            error: { code: 'VALIDATION_ERROR', message: 'Not an email address.', field: 'email' },
          }),
          { status: 422 },
        ),
    )

    const api = client()
    const failure = await api.request('/api/a').catch((cause: unknown) => cause)

    expect((failure as ApiError).field).toBe('email')
    expect((failure as ApiError).message).toBe('Not an email address.')
  })
})
