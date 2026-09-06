/** One question, asked correctly: did the service speak? */

/* The six copies this replaced asked `status < 500`, which answers a different question and gets
   both ends of it wrong. Both are asserted here: the rule is only worth having if it separates
   them. */

import { describe, expect, it } from 'vitest'

import { ApiError } from './client'
import { failureText, UNREACHABLE } from './failure'

describe('what a failure says', () => {
  // The end the old rule threw away. `errors.py` writes this sentence and puts a request id in it.
  it('repeats the service when the service answered, whatever the status', () => {
    const spoke = new ApiError(500, {
      code: 'INTERNAL_ERROR',
      message: 'The service failed to handle this request. Try again; quote request 7f3a.',
      field: null,
    })

    expect(failureText(spoke)).toContain('quote request 7f3a')
  })

  // And the end it invented. A gateway's 502 has no envelope, so `message` is the string `HTTP
  // 502` — which the old rule would have refused to print, correctly, for the wrong reason.
  it('does not put a gateway on screen as though it were the service', () => {
    expect(failureText(new ApiError(502, null))).toBe(UNREACHABLE)
    expect(failureText(new ApiError(502, null))).not.toContain('502')
  })

  it('says nothing was reached when nothing was', () => {
    expect(failureText(new TypeError('Failed to fetch'))).toBe(UNREACHABLE)
    expect(failureText(undefined)).toBe(UNREACHABLE)
  })

  // A screen with something to add about what the silence means for it passes its own.
  it('lets a screen say what the silence cost it', () => {
    const mine = 'The service could not be reached. The subscription was not changed.'
    expect(failureText(new TypeError('x'), mine)).toBe(mine)
  })

  it('falls back when the envelope came back empty-handed', () => {
    expect(
      failureText(new ApiError(403, { code: 'PERMISSION_DENIED', message: '', field: null })),
    ).toBe(UNREACHABLE)
  })
})
