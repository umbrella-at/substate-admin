/** A failure, as a sentence, in one place. There were six copies of the five lines below. */

/* WHAT IS BEING ASKED IS WHETHER THE SERVICE SPOKE, NOT WHAT IT ANSWERED. Every copy tested
   `status < 500`, and that gets both ends wrong. */

/* A 500 carrying the backend's own envelope did speak — `errors.py` writes a sentence for it,
   naming the request id — and the test threw it away for a claim about the network that is false. */

/* A 502 from a gateway did not speak, and arrives as an `ApiError` all the same. `code` is the
   honest test: the client sets it to `UNKNOWN` exactly when no envelope came back. */

import { ApiError } from '@/api/client'

/** What to say when nothing answered. A screen with something to add about what that means for
 *  it — that nothing was sent, that nothing was changed — passes its own. */
export const UNREACHABLE = 'The service could not be reached.'

export function failureText(cause: unknown, unreachable: string = UNREACHABLE): string {
  if (cause instanceof ApiError && cause.code !== 'UNKNOWN' && cause.message !== '') {
    return cause.message
  }
  return unreachable
}
